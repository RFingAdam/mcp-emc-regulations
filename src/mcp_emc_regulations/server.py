"""MCP server for EMC/RF regulatory lookup."""
import json
from pathlib import Path
from typing import Any

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

DATA_DIR = Path(__file__).parent / "data"

# Load data files
def load_json(filename: str) -> dict:
    filepath = DATA_DIR / filename
    if filepath.exists():
        return json.loads(filepath.read_text())
    return {}

PART15_LIMITS = load_json("part15_limits.json")
RESTRICTED_BANDS = load_json("restricted_bands.json")

server = Server("mcp-emc-regulations")


def format_limit_result(limit: dict, section: str) -> str:
    """Format a limit entry for display."""
    freq_range = f"{limit.get('freq_min_mhz', '?')} - {limit.get('freq_max_mhz', '?')} MHz"

    if 'limit_dbuv_m' in limit:
        value = f"{limit['limit_dbuv_m']} dBuV/m"
    elif 'limit_uv_m' in limit:
        value = f"{limit['limit_uv_m']} uV/m ({limit.get('limit_dbuv_m', '?')} dBuV/m)"
    elif 'limit_dbuv' in limit:
        value = f"{limit['limit_dbuv']} dBuV"
    elif 'limit_dbuv_qp' in limit:
        value = f"QP: {limit['limit_dbuv_qp']} dBuV, Avg: {limit.get('limit_dbuv_avg', '?')} dBuV"
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


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="fcc_part15_limit",
            description="Get FCC Part 15 emission limits for a frequency. Returns Class A and/or Class B limits for unintentional radiators (15.109), intentional radiators (15.209), or conducted emissions (15.207).",
            inputSchema={
                "type": "object",
                "properties": {
                    "frequency_mhz": {
                        "type": "number",
                        "description": "Frequency in MHz to look up limits for"
                    },
                    "section": {
                        "type": "string",
                        "enum": ["15.109", "15.207", "15.209", "all"],
                        "description": "Which section to query: 15.109 (radiated unintentional), 15.207 (conducted), 15.209 (radiated intentional), or 'all'"
                    },
                    "device_class": {
                        "type": "string",
                        "enum": ["A", "B", "both"],
                        "description": "Device class: A (commercial), B (residential), or both"
                    }
                },
                "required": ["frequency_mhz"]
            }
        ),
        Tool(
            name="fcc_restricted_bands",
            description="Check if a frequency falls within FCC Part 15.205 restricted bands where intentional radiators are prohibited.",
            inputSchema={
                "type": "object",
                "properties": {
                    "frequency_mhz": {
                        "type": "number",
                        "description": "Frequency in MHz to check"
                    }
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
                    "freq_min_mhz": {
                        "type": "number",
                        "description": "Optional: only show bands above this frequency"
                    },
                    "freq_max_mhz": {
                        "type": "number",
                        "description": "Optional: only show bands below this frequency"
                    }
                }
            }
        ),
        Tool(
            name="emc_get_limit",
            description="Get emission or immunity limit for a specific frequency and standard. Supports FCC Part 15, CISPR, and other standards.",
            inputSchema={
                "type": "object",
                "properties": {
                    "frequency_mhz": {
                        "type": "number",
                        "description": "Frequency in MHz"
                    },
                    "standard": {
                        "type": "string",
                        "description": "Standard to query (e.g., 'FCC Part 15.109', 'FCC Part 15.209', 'CISPR 32')"
                    },
                    "device_class": {
                        "type": "string",
                        "description": "Device class if applicable (e.g., 'A', 'B', 'Class 1', 'Class 5')"
                    }
                },
                "required": ["frequency_mhz", "standard"]
            }
        ),
        Tool(
            name="emc_standards_list",
            description="List all available EMC standards and regulations in the database.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="ecfr_query",
            description="Query the eCFR API for specific CFR sections. Returns the regulatory text for a given title and part.",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {
                        "type": "integer",
                        "description": "CFR title number (e.g., 47 for FCC regulations)"
                    },
                    "part": {
                        "type": "integer",
                        "description": "CFR part number (e.g., 15 for Part 15)"
                    },
                    "section": {
                        "type": "string",
                        "description": "Optional: specific section number (e.g., '15.209')"
                    }
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

        results = []
        results.append(f"FCC Part 15 Limits at {freq_mhz} MHz\n{'='*40}")

        # Section 15.109 - Radiated unintentional
        if section in ["15.109", "all"]:
            sec_data = PART15_LIMITS.get("section_15_109", {})
            results.append(f"\n## Section 15.109 - {sec_data.get('title', 'Radiated Emission Limits')}")

            if device_class in ["A", "both"]:
                class_a = sec_data.get("class_a", {})
                limit = find_limit_for_frequency(class_a.get("limits", []), freq_mhz)
                if limit:
                    results.append(f"\nClass A ({class_a.get('description', 'Commercial')}):")
                    results.append(format_limit_result(limit, "15.109"))
                else:
                    results.append("\nClass A: No limit defined for this frequency")

            if device_class in ["B", "both"]:
                class_b = sec_data.get("class_b", {})
                limit = find_limit_for_frequency(class_b.get("limits", []), freq_mhz)
                if limit:
                    results.append(f"\nClass B ({class_b.get('description', 'Residential')}):")
                    results.append(format_limit_result(limit, "15.109"))
                else:
                    results.append("\nClass B: No limit defined for this frequency")

        # Section 15.207 - Conducted
        if section in ["15.207", "all"]:
            sec_data = PART15_LIMITS.get("section_15_207", {})
            if freq_mhz <= 30:  # Conducted limits only apply up to 30 MHz
                results.append(f"\n## Section 15.207 - {sec_data.get('title', 'Conducted Limits')}")

                if device_class in ["A", "both"]:
                    class_a = sec_data.get("class_a", {})
                    limit = find_limit_for_frequency(class_a.get("limits", []), freq_mhz)
                    if limit:
                        results.append("\nClass A:")
                        results.append(format_limit_result(limit, "15.207"))

                if device_class in ["B", "both"]:
                    class_b = sec_data.get("class_b", {})
                    limit = find_limit_for_frequency(class_b.get("limits", []), freq_mhz)
                    if limit:
                        results.append("\nClass B:")
                        results.append(format_limit_result(limit, "15.207"))

        # Section 15.209 - Radiated intentional
        if section in ["15.209", "all"]:
            sec_data = PART15_LIMITS.get("section_15_209", {})
            results.append(f"\n## Section 15.209 - {sec_data.get('title', 'Intentional Radiators')}")
            limit = find_limit_for_frequency(sec_data.get("limits", []), freq_mhz)
            if limit:
                results.append(format_limit_result(limit, "15.209"))
            else:
                results.append("  No limit defined for this frequency")

        # Check restricted bands
        restricted = check_restricted_band(freq_mhz)
        if restricted:
            results.append(f"\n⚠️  WARNING: {freq_mhz} MHz is in a RESTRICTED BAND (15.205)")
            results.append(f"   {restricted['freq_min_mhz']} - {restricted['freq_max_mhz']} MHz: {restricted['service']}")

        return [TextContent(type="text", text="\n".join(results))]

    elif name == "fcc_restricted_bands":
        freq_mhz = arguments["frequency_mhz"]
        restricted = check_restricted_band(freq_mhz)

        if restricted:
            result = f"⚠️  RESTRICTED BAND\n\n"
            result += f"Frequency {freq_mhz} MHz falls within a restricted band per 47 CFR 15.205:\n\n"
            result += f"  Band: {restricted['freq_min_mhz']} - {restricted['freq_max_mhz']} MHz\n"
            result += f"  Protected Service: {restricted['service']}\n\n"
            result += "Intentional radiators are generally prohibited from operating in this band.\n"
            result += "See 15.205(c) and 15.205(d) for limited exceptions."
        else:
            result = f"✓ CLEAR\n\n"
            result += f"Frequency {freq_mhz} MHz is NOT in a restricted band.\n"
            result += "Normal Part 15.209 emission limits apply for intentional radiators."

        return [TextContent(type="text", text=result)]

    elif name == "fcc_restricted_bands_list":
        freq_min = arguments.get("freq_min_mhz", 0)
        freq_max = arguments.get("freq_max_mhz", float('inf'))

        bands = RESTRICTED_BANDS.get('restricted_bands', [])
        filtered = [b for b in bands if b['freq_max_mhz'] >= freq_min and b['freq_min_mhz'] <= freq_max]

        result = f"FCC Part 15.205 Restricted Bands\n{'='*50}\n\n"
        result += f"Showing {len(filtered)} bands"
        if freq_min > 0 or freq_max < float('inf'):
            result += f" (filtered: {freq_min} - {freq_max} MHz)"
        result += "\n\n"

        for band in filtered:
            result += f"  {band['freq_min_mhz']:>10.4f} - {band['freq_max_mhz']:<10.4f} MHz  |  {band['service']}\n"

        result += "\n" + "\n".join(RESTRICTED_BANDS.get('notes', []))

        return [TextContent(type="text", text=result)]

    elif name == "emc_get_limit":
        freq_mhz = arguments["frequency_mhz"]
        standard = arguments["standard"].lower()
        device_class = arguments.get("device_class", "B")

        # Route to appropriate handler based on standard
        if "fcc" in standard or "part 15" in standard or "15." in standard:
            # Determine section
            if "15.109" in standard:
                section = "15.109"
            elif "15.207" in standard:
                section = "15.207"
            elif "15.209" in standard:
                section = "15.209"
            else:
                section = "all"

            # Recursively call fcc_part15_limit
            return await call_tool("fcc_part15_limit", {
                "frequency_mhz": freq_mhz,
                "section": section,
                "device_class": device_class.upper() if device_class else "both"
            })
        else:
            return [TextContent(type="text", text=f"Standard '{standard}' not yet implemented. Available: FCC Part 15.109, 15.207, 15.209")]

    elif name == "emc_standards_list":
        result = "Available EMC Standards and Regulations\n" + "="*45 + "\n\n"

        result += "## FCC (United States)\n"
        result += "  - Part 15.109 - Radiated emissions (unintentional radiators)\n"
        result += "  - Part 15.207 - Conducted emissions\n"
        result += "  - Part 15.209 - Radiated emissions (intentional radiators)\n"
        result += "  - Part 15.205 - Restricted frequency bands\n\n"

        result += "## Coming Soon\n"
        result += "  - FCC Part 18 - ISM equipment\n"
        result += "  - CISPR 11 - Industrial, scientific, medical equipment\n"
        result += "  - CISPR 22/32 - Information technology equipment\n"
        result += "  - CISPR 25 - Automotive components\n"
        result += "  - IEC 60601-1-2 - Medical electrical equipment\n"
        result += "  - 3GPP LTE/NR band specifications\n"
        result += "  - PTCRB certification requirements\n"

        return [TextContent(type="text", text=result)]

    elif name == "ecfr_query":
        title = arguments["title"]
        part = arguments["part"]
        section = arguments.get("section")

        # Build eCFR API URL
        base_url = "https://www.ecfr.gov/api/versioner/v1/full"
        date = "current"

        if section:
            # Query specific section
            url = f"{base_url}/{date}/title-{title}.json?part={part}&section={section}"
        else:
            # Query entire part structure
            url = f"https://www.ecfr.gov/api/versioner/v1/structure/{date}/title-{title}.json?part={part}"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, timeout=30.0)

                if response.status_code == 200:
                    data = response.json()
                    # Format the response
                    result = f"eCFR Query: Title {title}, Part {part}"
                    if section:
                        result += f", Section {section}"
                    result += f"\n{'='*50}\n\n"
                    result += json.dumps(data, indent=2)[:8000]  # Truncate if too long
                    if len(json.dumps(data)) > 8000:
                        result += "\n\n[Output truncated - full response available via direct API query]"
                else:
                    result = f"eCFR API returned status {response.status_code}: {response.text[:500]}"
        except Exception as e:
            result = f"Error querying eCFR API: {str(e)}"

        return [TextContent(type="text", text=result)]

    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def run():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )


def main():
    import asyncio
    asyncio.run(run())


if __name__ == "__main__":
    main()
