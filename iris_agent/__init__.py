"""IRIS agentic workflow (LangGraph). See README.md."""
import sys

# Importing the existing engine code (demo/staged_walkthrough, iris/lib) must never write
# __pycache__ into the read-only repo.
sys.dont_write_bytecode = True
