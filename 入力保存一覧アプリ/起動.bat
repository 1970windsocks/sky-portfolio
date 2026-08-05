@echo off
cd /d "%~dp0"
py -3.12 -m streamlit run app.py
pause
