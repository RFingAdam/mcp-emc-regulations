"""MCP server for EMC/RF regulatory lookup."""
import json
from pathlib import Path
from typing import Any

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

DATA_DIR = Path(__file__).parent / "data"


def load_json(filename: str) -> dict:
    """Load a JSON data file."""
    filepath = DATA_DIR / filename
    if filepath.exists():
        return json.loads(filepath.read_text())
    return {}


# Load all data files
PART15_LIMITS = load_json("part15_limits.json")
PART18_LIMITS = load_json("part18_limits.json")
RESTRICTED_BANDS = load_json("restricted_bands.json")
CISPR_LIMITS = load_json("cispr_limits.json")
LTE_BANDS = load_json("lte_bands.json")
NR_BANDS = load_json("nr_bands.json")

server = Server("mcp-emc-regulations")


def format_limit_result(limit: dict, section: str = "") -> str:
    """Format a limit entry for display."""
    freq_range = f"{limit.get('freq_min_mhz', '?')} - {limit.get('freq_max_mhz', '?')} MHz"

    if 'limit_dbuv_m' in limit:
        value = f"{limit['limit_dbuv_m']} dBuV/m"
    elif 'limit_uv_m' in limit:
        value = f"{limit['limit_uv_m']} uV/m ({limit.get('limit_dbuv_m', '?')} dBuV/m)"
    elif 'limit_dbuv' in limit:
        value = f"{limit['limit_dbuv']} dBuV"
    elif 'limit_dbuv_qp' in limit:
        value = f"QP: {limit['limit_dbuv_qp']} dBuV/m, Avg: {limit.get('limit_dbuv_avg', '?')} dBuV/m"
    else:
        value = "See notes"

    distance = f"@ {limit['distance_m']}m" if 'distance_m' in limit else ""
    detector = f"({limit['detector']})" if 'detector' in limit else ""
    notes = f" - {limit['notes']}" if 'notes' in limit else ""

    return f"  {freq_range}: {value} {distance} {detector}{notes}"


def find_limit_for_frequency(limits: list, freq_mhz: float) -> dict | None:
    """Find the applicable limit for a given frequency."""
    for limit in limits:
        if limit['freq_min_mhz'] <= freq_mhz < limit['freq_max_mhz']:
            return limit
    return None


def check_restricted_band(freq_mhz: float) -> dict | None:
    """Check if frequency is in a restricted band."""
    bands = RESTRICTED_BANDS.get('restricted_bands', [])
    for band in bands:
        if band['freq_min_mhz'] <= freq_mhz <= band['freq_max_mhz']:
            return band
    return None


def check_ism_band(freq_mhz: float) -> dict | None:
    """Check if frequency is in an ISM band."""
    ism_bands = PART18_LIMITS.get('ism_bands', {}).get('bands', [])
    for band in ism_bands:
        range_mhz = band.get('range_mhz', [0, 0])
        if range_mhz[0] <= freq_mhz <= range_mhz[1]:
            return band
    return None


def find_lte_band(band_num: int) -> dict | None:
    """Find LTE band by number."""
    bands = LTE_BANDS.get('bands', [])
    for band in bands:
        if band['band'] == band_num:
            return band
    return None


def find_nr_band(band_name: str) -> dict | None:
    """Find NR band by name (e.g., 'n77')."""
    band_name = band_name.lower()
    for band in NR_BANDS.get('fr1_bands', {}).get('bands', []):
        if band['band'].lower() == band_name:
            return band
    for band in NR_BANDS.get('fr2_bands', {}).get('bands', []):
        if band['band'].lower() == band_name:
            return band
    return None


def get_cispr_limit(standard: str, device_class: str, freq_mhz: float, emission_type: str = "radiated") -> str:
    """Get CISPR emission limit."""
    standard = standard.lower()
    device_class = device_class.lower()

    if "32" in standard or "22" in standard:
        data = CISPR_LIMITS.get('cispr_32', {})
    elif "11" in standard:
        data = CISPR_LIMITS.get('cispr_11', {})
    elif "14" in standard:
        data = CISPR_LIMITS.get('cispr_14_1', {})
    else:
        return f"Unknown CISPR standard: {standard}"

    class_key = f"class_{device_class}" if device_class in ['a', 'b'] else 'class_b'
    class_data = data.get(class_key, data.get('group_1', {}).get(class_key, {}))

    if not class_data:
        return f"No data for {standard} Class {device_class.upper()}"

    result = f"CISPR {standard.upper()} Class {device_class.upper()} at {freq_mhz} MHz\n{'='*50}\n\n"

    if emission_type == "radiated":
        rad_data = class_data.get('radiated_emissions', {})
        limits = rad_data.get('limits', [])
        limit = find_limit_for_frequency(limits, freq_mhz)

        if limit:
            result += f"Radiated Emissions (@ {rad_data.get('measurement_distance_m', '?')}m):\n"
            result += format_limit_result(limit)
        else:
            # Check above 1 GHz limits
            above_1g = rad_data.get('above_1ghz', {})
            if above_1g and freq_mhz >= 1000:
                limits = above_1g.get('limits', [])
                limit = find_limit_for_frequency(limits, freq_mhz)
                if limit:
                    result += f"Radiated Emissions >1GHz (@ {above_1g.get('measurement_distance_m', '?')}m):\n"
                    result += format_limit_result(limit)
            else:
                result += "No radiated limit found for this frequency"
    else:
        cond_data = class_data.get('conducted_emissions', {})
        limits = cond_data.get('limits', [])
        limit = find_limit_for_frequency(limits, freq_mhz)

        if limit:
            result += f"Conducted Emissions ({cond_data.get('port', 'AC mains')}):\n"
            result += format_limit_result(limit)
        else:
            result += "No conducted limit found for this frequency"

    return result


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="fcc_part15_limit",
            description="Get FCC Part 15 emission limits for a frequency. Returns Class A and/or Class B limits for unintentional radiators (15.109), intentional radiators (15.209), or conducted emissions (15.207).",
            inputSchema={
                "type": "object",
                "properties": {
                    "frequency_mhz": {"type": "number", "description": "Frequency in MHz"},
                    "section": {"type": "string", "enum": ["15.109", "15.207", "15.209", "all"], "description": "Section to query"},
                    "device_class": {"type": "string", "enum": ["A", "B", "both"], "description": "Device class"}
                },
                "required": ["frequency_mhz"]
            }
        ),
        Tool(
            name="fcc_part18_limit",
            description="Get FCC Part 18 (ISM equipment) emission limits. Check ISM bands and limits for industrial/consumer ISM equipment.",
            inputSchema={
                "type": "object",
                "properties": {
                    "frequency_mhz": {"type": "number", "description": "Frequency in MHz"},
                    "equipment_type": {"type": "string", "enum": ["consumer", "industrial"], "description": "ISM equipment type"}
                },
                "required": ["frequency_mhz"]
            }
        ),
        Tool(
            name="fcc_restricted_bands",
            description="Check if a frequency falls within FCC Part 15.205 restricted bands.",
            inputSchema={
                "type": "object",
                "properties": {
                    "frequency_mhz": {"type": "number", "description": "Frequency in MHz to check"}
                },
                "required": ["frequency_mhz"]
            }
        ),
        Tool(
            name="fcc_restricted_bands_list",
            description="List all FCC Part 15.205 restricted frequency bands.",
            inputSchema={
                "type": "object",
                "properties": {
                    "freq_min_mhz": {"type": "number", "description": "Only show bands above this frequency"},
                    "freq_max_mhz": {"type": "number", "description": "Only show bands below this frequency"}
                }
            }
        ),
        Tool(
            name="ism_bands_list",
            description="List all ISM (Industrial, Scientific, Medical) frequency bands per ITU Radio Regulations.",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="cispr_limit",
            description="Get CISPR emission limits (CISPR 11, 22, 32, 14-1). Returns radiated or conducted limits for Class A or B.",
            inputSchema={
                "type": "object",
                "properties": {
                    "frequency_mhz": {"type": "number", "description": "Frequency in MHz"},
                    "standard": {"type": "string", "enum": ["CISPR 11", "CISPR 22", "CISPR 32", "CISPR 14-1"], "description": "CISPR standard"},
                    "device_class": {"type": "string", "enum": ["A", "B"], "description": "Device class"},
                    "emission_type": {"type": "string", "enum": ["radiated", "conducted"], "description": "Emission type"}
                },
                "required": ["frequency_mhz", "standard"]
            }
        ),
        Tool(
            name="emc_compare_limits",
            description="Compare emission limits between FCC and CISPR standards at a given frequency.",
            inputSchema={
                "type": "object",
                "properties": {
                    "frequency_mhz": {"type": "number", "description": "Frequency in MHz"},
                    "device_class": {"type": "string", "enum": ["A", "B"], "description": "Device class"}
                },
                "required": ["frequency_mhz"]
            }
        ),
        Tool(
            name="lte_band_lookup",
            description="Look up 3GPP LTE band information by band number. Returns frequencies, duplex mode, bandwidths.",
            inputSchema={
                "type": "object",
                "properties": {
                    "band": {"type": "integer", "description": "LTE band number (e.g., 7, 12, 41)"}
                },
                "required": ["band"]
            }
        ),
        Tool(
            name="lte_bands_list",
            description="List all LTE bands, optionally filtered by region or carrier.",
            inputSchema={
                "type": "object",
                "properties": {
                    "region": {"type": "string", "description": "Filter by region (Americas, Europe, APAC, Global)"},
                    "carrier": {"type": "string", "description": "Filter by US carrier (att, verizon, tmobile)"}
                }
            }
        ),
        Tool(
            name="nr_band_lookup",
            description="Look up 3GPP 5G NR band information by band name (e.g., n77, n260).",
            inputSchema={
                "type": "object",
                "properties": {
                    "band": {"type": "string", "description": "NR band name (e.g., 'n77', 'n260')"}
                },
                "required": ["band"]
            }
        ),
        Tool(
            name="nr_bands_list",
            description="List all 5G NR bands, optionally filtered by frequency range (FR1 sub-6GHz, FR2 mmWave).",
            inputSchema={
                "type": "object",
                "properties": {
                    "frequency_range": {"type": "string", "enum": ["FR1", "FR2", "all"], "description": "FR1 (sub-6), FR2 (mmWave), or all"},
                    "carrier": {"type": "string", "description": "Filter by US carrier (att, verizon, tmobile)"}
                }
            }
        ),
        Tool(
            name="frequency_to_band",
            description="Find which LTE/NR bands contain a given frequency.",
            inputSchema={
                "type": "object",
                "properties": {
                    "frequency_mhz": {"type": "number", "description": "Frequency in MHz"}
                },
                "required": ["frequency_mhz"]
            }
        ),
        Tool(
            name="emc_standards_list",
            description="List all available EMC standards and regulations in the database.",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="ecfr_query",
            description="Query the eCFR API for specific CFR sections.",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "integer", "description": "CFR title (47 for FCC)"},
                    "part": {"type": "integer", "description": "CFR part (15, 18, etc.)"},
                    "section": {"type": "string", "description": "Section number (e.g., '15.209')"}
                },
                "required": ["title", "part"]
            }
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:

    if name == "fcc_part15_limit":
        freq_mhz = arguments["frequency_mhz"]
        section = arguments.get("section", "all")
        device_class = arguments.get("device_class", "both")

        results = [f"FCC Part 15 Limits at {freq_mhz} MHz\n{'='*40}"]

        if section in ["15.109", "all"]:
            sec_data = PART15_LIMITS.get("section_15_109", {})
            results.append(f"\n## Section 15.109 - {sec_data.get('title', 'Radiated Emission Limits')}")

            if device_class in ["A", "both"]:
                class_a = sec_data.get("class_a", {})
                limit = find_limit_for_frequency(class_a.get("limits", []), freq_mhz)
                if limit:
                    results.append(f"\nClass A ({class_a.get('description', 'Commercial')}):")
                    results.append(format_limit_result(limit))

            if device_class in ["B", "both"]:
                class_b = sec_data.get("class_b", {})
                limit = find_limit_for_frequency(class_b.get("limits", []), freq_mhz)
                if limit:
                    results.append(f"\nClass B ({class_b.get('description', 'Residential')}):")
                    results.append(format_limit_result(limit))

        if section in ["15.207", "all"] and freq_mhz <= 30:
            sec_data = PART15_LIMITS.get("section_15_207", {})
            results.append(f"\n## Section 15.207 - {sec_data.get('title', 'Conducted Limits')}")

            if device_class in ["A", "both"]:
                limit = find_limit_for_frequency(sec_data.get("class_a", {}).get("limits", []), freq_mhz)
                if limit:
                    results.append("\nClass A:")
                    results.append(format_limit_result(limit))

            if device_class in ["B", "both"]:
                limit = find_limit_for_frequency(sec_data.get("class_b", {}).get("limits", []), freq_mhz)
                if limit:
                    results.append("\nClass B:")
                    results.append(format_limit_result(limit))

        if section in ["15.209", "all"]:
            sec_data = PART15_LIMITS.get("section_15_209", {})
            results.append(f"\n## Section 15.209 - {sec_data.get('title', 'Intentional Radiators')}")
            limit = find_limit_for_frequency(sec_data.get("limits", []), freq_mhz)
            if limit:
                results.append(format_limit_result(limit))

        restricted = check_restricted_band(freq_mhz)
        if restricted:
            results.append(f"\n⚠️  WARNING: {freq_mhz} MHz is in a RESTRICTED BAND (15.205)")
            results.append(f"   {restricted['freq_min_mhz']} - {restricted['freq_max_mhz']} MHz: {restricted['service']}")

        return [TextContent(type="text", text="\n".join(results))]

    elif name == "fcc_part18_limit":
        freq_mhz = arguments["frequency_mhz"]
        eq_type = arguments.get("equipment_type", "consumer")

        result = f"FCC Part 18 (ISM Equipment) at {freq_mhz} MHz\n{'='*50}\n\n"

        ism_band = check_ism_band(freq_mhz)
        if ism_band:
            result += f"✓ WITHIN ISM BAND\n"
            result += f"  Center: {ism_band['center_mhz']} MHz\n"
            result += f"  Range: {ism_band['range_mhz'][0]} - {ism_band['range_mhz'][1]} MHz\n"
            if 'notes' in ism_band:
                result += f"  Notes: {ism_band['notes']}\n"
            result += f"\n  Fundamental emissions: No limit within ISM band\n"
        else:
            result += f"✗ OUTSIDE ISM BANDS\n"
            result += f"  Standard emission limits apply (same as Part 15.209)\n\n"

        sec_data = PART18_LIMITS.get("section_18_305", {})
        eq_data = sec_data.get(f"{eq_type}_ism", {})
        limits = eq_data.get("emissions_outside_ism", [])
        limit = find_limit_for_frequency(limits, freq_mhz)

        if limit:
            result += f"\nLimits outside ISM bands ({eq_type.title()} ISM):\n"
            result += format_limit_result(limit)

        return [TextContent(type="text", text=result)]

    elif name == "fcc_restricted_bands":
        freq_mhz = arguments["frequency_mhz"]
        restricted = check_restricted_band(freq_mhz)

        if restricted:
            result = f"⚠️  RESTRICTED BAND\n\n"
            result += f"Frequency {freq_mhz} MHz falls within a restricted band per 47 CFR 15.205:\n\n"
            result += f"  Band: {restricted['freq_min_mhz']} - {restricted['freq_max_mhz']} MHz\n"
            result += f"  Protected Service: {restricted['service']}\n\n"
            result += "Intentional radiators are generally prohibited from operating in this band."
        else:
            result = f"✓ CLEAR\n\nFrequency {freq_mhz} MHz is NOT in a restricted band."

        return [TextContent(type="text", text=result)]

    elif name == "fcc_restricted_bands_list":
        freq_min = arguments.get("freq_min_mhz", 0)
        freq_max = arguments.get("freq_max_mhz", float('inf'))

        bands = RESTRICTED_BANDS.get('restricted_bands', [])
        filtered = [b for b in bands if b['freq_max_mhz'] >= freq_min and b['freq_min_mhz'] <= freq_max]

        result = f"FCC Part 15.205 Restricted Bands ({len(filtered)} bands)\n{'='*50}\n\n"
        for band in filtered:
            result += f"  {band['freq_min_mhz']:>10.4f} - {band['freq_max_mhz']:<10.4f} MHz  |  {band['service']}\n"

        return [TextContent(type="text", text=result)]

    elif name == "ism_bands_list":
        ism_bands = PART18_LIMITS.get('ism_bands', {}).get('bands', [])
        result = f"ISM Frequency Bands (ITU Radio Regulations)\n{'='*50}\n\n"

        for band in ism_bands:
            result += f"  {band['center_mhz']:>8} MHz  ({band['range_mhz'][0]}-{band['range_mhz'][1]} MHz)"
            if 'notes' in band:
                result += f"  [{band['notes']}]"
            result += "\n"

        return [TextContent(type="text", text=result)]

    elif name == "cispr_limit":
        freq_mhz = arguments["frequency_mhz"]
        standard = arguments["standard"]
        device_class = arguments.get("device_class", "B")
        emission_type = arguments.get("emission_type", "radiated")

        result = get_cispr_limit(standard, device_class, freq_mhz, emission_type)
        return [TextContent(type="text", text=result)]

    elif name == "emc_compare_limits":
        freq_mhz = arguments["frequency_mhz"]
        device_class = arguments.get("device_class", "B").upper()

        result = f"EMC Limit Comparison at {freq_mhz} MHz (Class {device_class})\n{'='*55}\n\n"

        # FCC Part 15.109
        fcc_data = PART15_LIMITS.get("section_15_109", {}).get(f"class_{device_class.lower()}", {})
        fcc_limit = find_limit_for_frequency(fcc_data.get("limits", []), freq_mhz)

        if fcc_limit:
            result += f"FCC Part 15.109 Class {device_class}:\n"
            result += f"  {fcc_limit['limit_dbuv_m']} dBuV/m @ {fcc_limit['distance_m']}m (QP)\n\n"

        # CISPR 32
        cispr_data = CISPR_LIMITS.get('cispr_32', {}).get(f"class_{device_class.lower()}", {})
        cispr_rad = cispr_data.get('radiated_emissions', {})
        cispr_limit = find_limit_for_frequency(cispr_rad.get('limits', []), freq_mhz)

        if cispr_limit:
            result += f"CISPR 32 Class {device_class}:\n"
            result += f"  {cispr_limit['limit_dbuv_m']} dBuV/m @ {cispr_rad.get('measurement_distance_m', 10)}m (QP)\n\n"

        # Distance correction note
        if fcc_limit and cispr_limit:
            result += "Note: FCC uses 3m, CISPR uses 10m measurement distance.\n"
            result += "Distance correction: +10.5 dB to convert 10m→3m limits.\n"
            cispr_at_3m = cispr_limit['limit_dbuv_m'] + 10.5
            result += f"CISPR 32 at 3m (calculated): {cispr_at_3m:.1f} dBuV/m\n"

        return [TextContent(type="text", text=result)]

    elif name == "lte_band_lookup":
        band_num = arguments["band"]
        band = find_lte_band(band_num)

        if band:
            result = f"LTE Band {band_num} ({band.get('name', 'Unknown')})\n{'='*40}\n\n"

            if band.get('uplink_mhz'):
                result += f"Uplink:   {band['uplink_mhz'][0]} - {band['uplink_mhz'][1]} MHz\n"
            if band.get('downlink_mhz'):
                result += f"Downlink: {band['downlink_mhz'][0]} - {band['downlink_mhz'][1]} MHz\n"

            result += f"Duplex:   {band.get('duplex', 'Unknown')}\n"
            result += f"Bandwidths: {', '.join(str(b) for b in band.get('bandwidth_mhz', []))} MHz\n"
            result += f"Regions:  {', '.join(band.get('regions', []))}\n"

            if 'notes' in band:
                result += f"Notes:    {band['notes']}\n"
        else:
            result = f"LTE Band {band_num} not found in database."

        return [TextContent(type="text", text=result)]

    elif name == "lte_bands_list":
        region = arguments.get("region", "").lower()
        carrier = arguments.get("carrier", "").lower()

        if carrier:
            carrier_bands = LTE_BANDS.get('us_carrier_bands', {}).get(carrier, {})
            if carrier_bands:
                result = f"LTE Bands for {carrier.upper()}\n{'='*40}\n\n"
                result += f"Primary bands: {', '.join(str(b) for b in carrier_bands.get('primary', []))}\n"
                result += f"LTE-M bands:   {', '.join(str(b) for b in carrier_bands.get('lte_m', []))}\n"
            else:
                result = f"Carrier '{carrier}' not found. Available: att, verizon, tmobile"
        else:
            bands = LTE_BANDS.get('bands', [])
            if region:
                bands = [b for b in bands if region in [r.lower() for r in b.get('regions', [])]]

            result = f"LTE Bands{' (' + region.title() + ')' if region else ''}\n{'='*50}\n\n"
            for band in bands[:30]:  # Limit output
                ul = band.get('uplink_mhz', [0, 0])
                dl = band.get('downlink_mhz', [0, 0])
                result += f"Band {band['band']:>2}: {dl[0]:>4}-{dl[1]:<4} MHz ({band['duplex']}) {band.get('name', '')}\n"

        return [TextContent(type="text", text=result)]

    elif name == "nr_band_lookup":
        band_name = arguments["band"]
        band = find_nr_band(band_name)

        if band:
            result = f"5G NR Band {band['band']} ({band.get('name', 'Unknown')})\n{'='*40}\n\n"

            if 'uplink_mhz' in band:
                result += f"Uplink:   {band['uplink_mhz'][0]} - {band['uplink_mhz'][1]} MHz\n"
                result += f"Downlink: {band['downlink_mhz'][0]} - {band['downlink_mhz'][1]} MHz\n"
            elif 'range_mhz' in band:
                result += f"Range:    {band['range_mhz'][0]} - {band['range_mhz'][1]} MHz\n"

            result += f"Duplex:   {band.get('duplex', 'Unknown')}\n"
            result += f"Max BW:   {band.get('max_bandwidth_mhz', '?')} MHz\n"

            if 'notes' in band:
                result += f"Notes:    {band['notes']}\n"
        else:
            result = f"NR Band '{band_name}' not found. Use format 'n77', 'n260', etc."

        return [TextContent(type="text", text=result)]

    elif name == "nr_bands_list":
        freq_range = arguments.get("frequency_range", "all").upper()
        carrier = arguments.get("carrier", "").lower()

        if carrier:
            carrier_bands = NR_BANDS.get('us_carrier_nr_bands', {}).get(carrier, {})
            if carrier_bands:
                result = f"5G NR Bands for {carrier.upper()}\n{'='*40}\n\n"
                result += f"Low-band:  {', '.join(carrier_bands.get('low_band', []))}\n"
                result += f"Mid-band:  {', '.join(carrier_bands.get('mid_band', []))}\n"
                result += f"mmWave:    {', '.join(carrier_bands.get('mmwave', []))}\n"
                if 'notes' in carrier_bands:
                    result += f"Notes:     {carrier_bands['notes']}\n"
            else:
                result = f"Carrier '{carrier}' not found."
        else:
            result = f"5G NR Bands\n{'='*50}\n\n"

            if freq_range in ["FR1", "ALL"]:
                result += "## FR1 (Sub-6 GHz)\n"
                for band in NR_BANDS.get('fr1_bands', {}).get('bands', []):
                    if 'uplink_mhz' in band:
                        result += f"  {band['band']:>4}: {band['uplink_mhz'][0]:>4}-{band['uplink_mhz'][1]:<4} MHz ({band['duplex']}) {band.get('name', '')}\n"

            if freq_range in ["FR2", "ALL"]:
                result += "\n## FR2 (mmWave)\n"
                for band in NR_BANDS.get('fr2_bands', {}).get('bands', []):
                    result += f"  {band['band']:>4}: {band['range_mhz'][0]:>5}-{band['range_mhz'][1]:<5} MHz {band.get('name', '')}\n"

        return [TextContent(type="text", text=result)]

    elif name == "frequency_to_band":
        freq_mhz = arguments["frequency_mhz"]
        found = []

        # Check LTE bands
        for band in LTE_BANDS.get('bands', []):
            ul = band.get('uplink_mhz')
            dl = band.get('downlink_mhz')
            if ul and ul[0] <= freq_mhz <= ul[1]:
                found.append(f"LTE Band {band['band']} (uplink)")
            if dl and dl[0] <= freq_mhz <= dl[1]:
                found.append(f"LTE Band {band['band']} (downlink)")

        # Check NR bands
        for band in NR_BANDS.get('fr1_bands', {}).get('bands', []):
            ul = band.get('uplink_mhz')
            dl = band.get('downlink_mhz')
            if ul and ul[0] <= freq_mhz <= ul[1]:
                found.append(f"NR {band['band']} (uplink)")
            if dl and dl[0] <= freq_mhz <= dl[1]:
                found.append(f"NR {band['band']} (downlink)")

        for band in NR_BANDS.get('fr2_bands', {}).get('bands', []):
            rng = band.get('range_mhz')
            if rng and rng[0] <= freq_mhz <= rng[1]:
                found.append(f"NR {band['band']}")

        result = f"Bands containing {freq_mhz} MHz\n{'='*40}\n\n"
        if found:
            for b in found:
                result += f"  - {b}\n"
        else:
            result += "  No LTE/NR bands found for this frequency.\n"

        # Also check ISM
        ism = check_ism_band(freq_mhz)
        if ism:
            result += f"\n  ISM Band: {ism['center_mhz']} MHz center\n"

        return [TextContent(type="text", text=result)]

    elif name == "emc_standards_list":
        result = "Available EMC Standards and Regulations\n" + "="*45 + "\n\n"

        result += "## FCC (United States)\n"
        result += "  ✓ Part 15.109 - Radiated emissions (unintentional)\n"
        result += "  ✓ Part 15.207 - Conducted emissions\n"
        result += "  ✓ Part 15.209 - Radiated emissions (intentional)\n"
        result += "  ✓ Part 15.205 - Restricted frequency bands\n"
        result += "  ✓ Part 18 - ISM equipment\n\n"

        result += "## CISPR (International)\n"
        result += "  ✓ CISPR 11 - Industrial, scientific, medical equipment\n"
        result += "  ✓ CISPR 32 - Multimedia equipment (replaces CISPR 22)\n"
        result += "  ✓ CISPR 14-1 - Household appliances\n\n"

        result += "## Cellular (3GPP)\n"
        result += "  ✓ LTE bands (E-UTRA)\n"
        result += "  ✓ 5G NR bands (FR1 + FR2)\n"
        result += "  ✓ US carrier band info (AT&T, Verizon, T-Mobile)\n\n"

        result += "## Coming Soon\n"
        result += "  - CISPR 25 - Automotive components\n"
        result += "  - IEC 60601-1-2 - Medical devices\n"
        result += "  - PTCRB certification requirements\n"

        return [TextContent(type="text", text=result)]

    elif name == "ecfr_query":
        title = arguments["title"]
        part = arguments["part"]
        section = arguments.get("section")

        if section:
            url = f"https://www.ecfr.gov/api/versioner/v1/full/current/title-{title}.json?part={part}&section={section}"
        else:
            url = f"https://www.ecfr.gov/api/versioner/v1/structure/current/title-{title}.json?part={part}"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, timeout=30.0)
                if response.status_code == 200:
                    data = response.json()
                    result = f"eCFR Query: Title {title}, Part {part}"
                    if section:
                        result += f", Section {section}"
                    result += f"\n{'='*50}\n\n"
                    result += json.dumps(data, indent=2)[:8000]
                else:
                    result = f"eCFR API returned status {response.status_code}"
        except Exception as e:
            result = f"Error querying eCFR API: {str(e)}"

        return [TextContent(type="text", text=result)]

    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def run():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main():
    import asyncio
    asyncio.run(run())


if __name__ == "__main__":
    main()
