@echo off
setlocal
cd /d "%~dp0"
echo Installing Logix Designer SDK wheel, mcp, fastmcp, lxml.
echo Note: Rockwell logix_designer_sdk 2.0.1 requires Python 3.12.x (not 3.13).
py -3.12 -m pip install "C:\Users\Public\Documents\Studio 5000\Logix Designer SDK\python\logix_designer_sdk-2.0.1-py3-none-any.whl"
if errorlevel 1 exit /b 1
py -3.12 -m pip install mcp fastmcp lxml
if errorlevel 1 exit /b 1
echo Done.
py -3.12 -m pip show logix-designer-sdk fastmcp mcp lxml
endlocal
