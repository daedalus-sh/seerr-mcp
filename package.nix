# seerr-mcp: the server, with its whole test suite in checkPhase: config,
# every tool against a fake Seerr shaped like v3.5.1's answers, and the MCP
# layer through the SDK's own client.
{
  lib,
  python3Packages,
}:

python3Packages.buildPythonApplication {
  pname = "seerr-mcp";
  version = "0.1.0";
  pyproject = true;

  src = lib.fileset.toSource {
    root = ./.;
    fileset = lib.fileset.unions [
      ./pyproject.toml
      ./README.md
      ./src
      ./tests
    ];
  };

  build-system = [ python3Packages.setuptools ];

  dependencies = with python3Packages; [
    httpx
    mcp
    starlette
    uvicorn
  ];

  nativeCheckInputs = [ python3Packages.pytestCheckHook ];

  pytestFlags = [
    "-p"
    "no:cacheprovider"
  ];

  pythonImportsCheck = [ "seerr_mcp" ];

  meta = {
    description = "MCP server for Seerr: search, see what is in the library and on its way, request movies and shows, report problems";
    homepage = "https://github.com/santiagotoscanini/seerr-mcp";
    license = lib.licenses.mit;
    mainProgram = "seerr-mcp";
    platforms = lib.platforms.linux;
  };
}
