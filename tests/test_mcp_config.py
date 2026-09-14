from pathlib import Path

from phenotyping_agent.mcp_tools import load_mcp_connections


def test_load_mcp_connections_maps_stdio_and_http(tmp_path: Path) -> None:
    mcp_json = tmp_path / "mcp.json"
    mcp_json.write_text(
        """
{
  "servers": {
    "r-tools": {
      "command": "Rscript",
      "args": ["--vanilla", "tools/server.R"]
    },
    "ohdsi_hecate": {
      "url": "https://example.org/mcp/sse",
      "type": "http"
    }
  }
}
""".strip(),
        encoding="utf-8",
    )

    root = Path("E:/git/PhenotypingAgent")
    out = load_mcp_connections(mcp_json, root)

    assert out["r-tools"]["transport"] == "stdio"
    assert out["r-tools"]["cwd"] == str(root)
    assert out["ohdsi_hecate"]["transport"] == "http"
    assert out["ohdsi_hecate"]["url"].startswith("https://")

