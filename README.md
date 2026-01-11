<p align="center">
  <img src="assets/logo.svg" alt="MCP EMC Regulations" width="420">
</p>

<p align="center">
  <strong>EMC/RF regulatory lookup for engineers via MCP</strong>
</p>

<p align="center">
  <a href="#features">Features</a> •
  <a href="#installation">Installation</a> •
  <a href="#tools">Tools</a> •
  <a href="#examples">Examples</a>
</p>

---

An MCP server providing instant access to EMC emission limits, frequency allocations, restricted bands, and compliance requirements. Query FCC Part 15, CISPR, automotive, medical, and cellular standards directly from Claude Code.

## Features

### Currently Available
- **FCC Part 15.109** - Radiated emission limits (Class A/B unintentional radiators)
- **FCC Part 15.207** - Conducted emission limits
- **FCC Part 15.209** - Radiated emission limits (intentional radiators)
- **FCC Part 15.205** - Restricted frequency bands lookup
- **eCFR API** - Query live regulatory text from the Code of Federal Regulations

### Coming Soon
- FCC Part 18 (ISM equipment)
- CISPR 11/22/32 (ITE emissions)
- CISPR 25 (Automotive components)
- IEC 60601-1-2 (Medical devices)
- 3GPP LTE/NR band specifications
- PTCRB/carrier certification requirements
- Limit comparison tools

## Installation

### 1. Clone and install

```bash
git clone https://github.com/RFingAdam/mcp-emc-regulations.git
cd mcp-emc-regulations
uv pip install -e .
```

### 2. Add to Claude Code

```bash
claude mcp add emc-regulations -- uv run --directory /path/to/mcp-emc-regulations mcp-emc-regulations
```

Or manually add to `~/.claude.json`:

```json
{
  "mcpServers": {
    "emc-regulations": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/mcp-emc-regulations", "mcp-emc-regulations"]
    }
  }
}
```

### 3. Restart Claude Code

## Tools

### `fcc_part15_limit`
Get FCC Part 15 emission limits for a specific frequency.

**Parameters:**
- `frequency_mhz` (required): Frequency in MHz
- `section`: Which section (15.109, 15.207, 15.209, or "all")
- `device_class`: "A" (commercial), "B" (residential), or "both"

### `fcc_restricted_bands`
Check if a frequency falls within a restricted band (15.205).

**Parameters:**
- `frequency_mhz` (required): Frequency to check

### `fcc_restricted_bands_list`
List all restricted frequency bands per 15.205.

**Parameters:**
- `freq_min_mhz`: Only show bands above this frequency
- `freq_max_mhz`: Only show bands below this frequency

### `emc_get_limit`
Universal limit lookup across standards.

**Parameters:**
- `frequency_mhz` (required): Frequency in MHz
- `standard` (required): Standard name (e.g., "FCC Part 15.109")
- `device_class`: Device classification if applicable

### `emc_standards_list`
List all available EMC standards in the database.

### `ecfr_query`
Query the eCFR API for CFR regulatory text.

**Parameters:**
- `title` (required): CFR title (e.g., 47 for FCC)
- `part` (required): CFR part (e.g., 15)
- `section`: Specific section number

## Examples

### Check Part 15 Class B limits at 100 MHz

```
Claude, what are the FCC Part 15 Class B emission limits at 100 MHz?
```

Response includes:
- 15.109 radiated limits (40 dBuV/m @ 3m for Class B)
- 15.209 intentional radiator limits
- Warning if frequency is in a restricted band

### Check if a frequency is restricted

```
Is 121.5 MHz a restricted band for Part 15 devices?
```

Response: Yes - aeronautical emergency frequency, intentional radiators prohibited.

### Compare Class A vs Class B

```
Compare FCC Class A and Class B radiated limits at 500 MHz
```

Shows both limits side-by-side with measurement distances.

## Data Sources

| Source | Type | Coverage |
|--------|------|----------|
| eCFR API | Live | 47 CFR Parts 15, 18, 22, etc. |
| Curated JSON | Local | Structured limit tables |
| FCC KDB | Reference | Guidance documents |

## Contributing

PRs welcome for adding new standards or improving data accuracy. Key areas:
- CISPR limit tables
- Automotive EMC (CISPR 25)
- Medical EMC (IEC 60601-1-2)
- Cellular band data (3GPP)

## License

MIT
