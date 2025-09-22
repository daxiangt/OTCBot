import asyncio
import aiohttp
import logging

# Set up a logger for this module
logger = logging.getLogger(__name__)

# Base URL for the Deribit API
DERIBIT_API_URL = "https://www.deribit.com/api/v2"

async def get_instrument_mark_price_async(session: aiohttp.ClientSession, instrument_name: str) -> tuple[str, float | None, float | None]:
    """
    Asynchronously fetches the mark price and index price for a single options contract.

    Args:
        session: An aiohttp.ClientSession object.
        instrument_name: The name of the options contract.

    Returns:
        A tuple containing (instrument_name, mark_price, index_price). Prices are None on failure.
    """
    url = f"{DERIBIT_API_URL}/public/ticker?instrument_name={instrument_name}"
    try:
        async with session.get(url, timeout=10) as response:
            response.raise_for_status()
            data = await response.json()
            if 'result' in data and 'mark_price' in data['result']:
                mark_price = data['result']['mark_price']
                index_price = data['result'].get('index_price') # Use .get() for safety
                return instrument_name, mark_price, index_price
            else:
                logger.error(f"Could not find 'mark_price' in API response for {instrument_name}.")
                return instrument_name, None, None
    except Exception as e:
        logger.error(f"An error occurred while requesting data for {instrument_name}: {e}")
        return instrument_name, None, None

def parse_leg_string(leg_string: str) -> dict | None:
    """
    Parses a string representing an option leg.
    Example: '+1 BTC-26SEP25-80000-P' -> {'instrument': 'BTC-26SEP25-80000-P', 'side': 'buy', 'quantity': 1}
             '-2 ETH-27JUN25-4000-C'  -> {'instrument': 'ETH-27JUN25-4000-C', 'side': 'sell', 'quantity': 2}
             '+1 26SEP25-95000-P'    -> Defaults to BTC: {'instrument': 'BTC-26SEP25-95000-P', 'side': 'buy', 'quantity': 1}
             '+1 26SEP25-95-P'       -> Corrects to BTC and adds '000': {'instrument': 'BTC-26SEP25-95000-P', 'side': 'buy', 'quantity': 1}
             '1 26SEP25-95000-P'     -> Corrects to a buy: {'instrument': 'BTC-26SEP25-95000-P', 'side': 'buy', 'quantity': 1}

    Args:
        leg_string: A string in the format '[+/-]qty instrument'.

    Returns:
        A dictionary with instrument, side, and quantity, or None if the format is incorrect.
    """
    parts = leg_string.strip().upper().split()
    if len(parts) < 2:
        logger.error(f"Format Error: '{leg_string}'. Input is too short.")
        return None

    qty_str = parts[0]
    instrument_parts = parts[1:]

    # --- Handle different instrument formats ---
    # Case 1: Standard format, e.g., "+1 BTC-26SEP25-130000-C"
    if len(instrument_parts) == 1:
        instrument = instrument_parts[0]
    # Case 2: Spaced-out format, e.g., "+1 BTC 26SEP25 130000 C"
    elif len(instrument_parts) == 4:
        instrument = "-".join(instrument_parts)
    # Case 3: Spaced-out format with no currency, e.g., "+1 26SEP25 130000 C"
    elif len(instrument_parts) == 3:
        instrument = "-".join(instrument_parts)
    else:
        logger.error(f"Format Error: '{leg_string}'. Invalid instrument format.")
        return None

    # --- Auto-correction and Validation for Quantity ---
    if not (qty_str.startswith('+') or qty_str.startswith('-')):
        # If the user enters "1 BTC..." instead of "+1 BTC...", attempt to correct it.
        # Heuristic: check if qty is a digit and instrument looks like a contract name.
        if qty_str.isdigit() and instrument.count('-') >= 2:
            logger.warning(f"Quantity '{qty_str}' should start with '+' or '-'. Assuming a buy ('+').")
            qty_str = f"+{qty_str}"
        else:
            logger.error(f"Format Error: '{leg_string}'. Quantity must start with '+' or '-'.")
            return None

    # --- Default to BTC if no currency is specified ---
    # Heuristic: Assumes Deribit format is CURRENCY-EXPIRY-STRIKE-TYPE.
    # If the instrument name doesn't start with a known currency, prepend "BTC-".
    if not (instrument.startswith("BTC-") or instrument.startswith("ETH-") or instrument.startswith("USDC-")):
        instrument = f"BTC-{instrument}"

    # --- Handle abbreviated BTC strike price (e.g., 95 for 95000) ---
    # This logic applies only if the instrument is for BTC.
    if instrument.startswith("BTC-"):
        try:
            parts = instrument.split('-')
            # Expected format: BTC-EXPIRY-STRIKE-TYPE (4 parts)
            if len(parts) == 4:
                strike_str = parts[2]
                # If strike is a number and seems abbreviated (e.g., <= 3 digits), add "000"
                if strike_str.isdigit() and len(strike_str) <= 3:
                    parts[2] = f"{strike_str}000"
                    instrument = "-".join(parts)
        except Exception as e:
            logger.warning(f"Could not process strike abbreviation for '{instrument}': {e}")

    # --- Final Parsing ---
    try:
        side = 'buy' if qty_str.startswith('+') else 'sell'
        quantity = int(qty_str[1:])
        if quantity <= 0:
            raise ValueError("Quantity must be a positive number")
        return {'instrument': instrument.upper(), 'side': side, 'quantity': quantity}
    except ValueError:
        logger.error(f"Format Error: '{leg_string}'. Quantity must be a valid positive integer.")
        return None

async def mark_px(strategy_legs_input: list[str]) -> str:
    """
    Parses a list of strategy leg strings, fetches their mark prices concurrently,
    and returns a formatted string with the calculated net price.

    Args:
        strategy_legs_input: A list of strings, where each string represents a strategy leg.
                             e.g., ["+1 BTC-26SEP25-95000-P", "-2 BTC-26SEP25-130000-C"]

    Returns:
        A formatted string containing the price details and net mark price, or an error message.
    """
    # --- 1. Parse the input strings into a structured list of dictionaries ---
    strategy_legs = []
    for leg_str in strategy_legs_input:
        parsed_leg = parse_leg_string(leg_str)
        if parsed_leg:
            strategy_legs.append(parsed_leg)
        else:
            # If parsing fails for any leg, abort the process.
            logger.error(f"Aborting due to invalid leg format: '{leg_str}'")
            return f"Error: Invalid leg format: '{leg_str}'"
    
    if not strategy_legs:
        logger.error("No valid strategy legs defined after parsing.")
        return "Error: No valid strategy legs provided."

    # --- 2. Enforce that all legs must have the same underlying asset ---
    first_underlying = None
    for leg in strategy_legs:
        # Extract the underlying currency from the instrument name (e.g., 'BTC' from 'BTC-26SEP25-95000-P')
        current_underlying = leg['instrument'].split('-')[0]
        if not first_underlying:
            first_underlying = current_underlying
        elif first_underlying != current_underlying:
            logger.error(f"All strategy legs must have the same underlying currency. Found '{first_underlying}' and '{current_underlying}'.")
            return f"Error: All legs must have the same underlying currency. Found '{first_underlying}' and '{current_underlying}'."
    # --- End of underlying asset consistency check ---

    # --- 3. Concurrently execute all API requests ---
    async with aiohttp.ClientSession() as session:
        # Use the parsed 'strategy_legs' list here
        tasks = [get_instrument_mark_price_async(session, leg['instrument']) for leg in strategy_legs]
        results = await asyncio.gather(*tasks)

    # --- 4. Process results and calculate the total strategy price ---
    price_map = {}
    index_price = None
    for i, (instrument, mark_price, idx_px) in enumerate(results):
        price_map[instrument] = mark_price
        # Grab the index price from the first successful API call
        if i == 0 and idx_px is not None:
            index_price = idx_px

    total_strategy_mark_price = 0.0
    price_details = []
    all_legs_fetched_successfully = True

    # Iterate over the structured 'strategy_legs' list for calculation
    for leg in strategy_legs:
        instrument = leg['instrument']
        mark_price = price_map.get(instrument)

        if mark_price is not None:
            leg_price = mark_price * leg['quantity']
            if leg['side'] == 'sell':
                leg_price = -leg_price
            
            total_strategy_mark_price += leg_price
            price_details.append(f" {leg['side'].upper():<4} {leg['quantity']}x {instrument:<22}: {mark_price:.4f}")
        else:
            # If a leg fails, mark the overall calculation as unsuccessful but continue processing others.
            all_legs_fetched_successfully = False
            price_details.append(f" {leg['side'].upper():<4} {leg['quantity']}x {instrument:<22}: ERROR (Price not found)")

    # --- 5. Format the final result string ---
    output_lines = ["Combo Mark Price per unit\n"]
    for detail in price_details:
        output_lines.append(detail)
    
    output_lines.append("\n" + "-" * 40)
    if all_legs_fetched_successfully:
        index_price_str = f"{index_price:,.0f}" if index_price is not None else "N/A"
        output_lines.append(f"  Net Combo Mark: {total_strategy_mark_price:.4f} {first_underlying}\n"
                            f"  Index Ref: ${index_price_str}")
    else:
        output_lines.append("  Net Combo Mark: N/A (Could not fetch price for all legs)")

    return "\n".join(output_lines)


if __name__ == "__main__":
    async def main():
        # Example usage of the refactored mark_px function
        example_legs = [
            "+1 26DEC25 95 P",      # Will default to BTC
            "-2 26SEP25 130 C",
        ]
        result_string = await mark_px(example_legs)
        print(result_string)

    # Basic logging configuration for standalone script execution
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    asyncio.run(main())
