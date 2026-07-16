# /// script
# requires-python = ">=3.12,<3.14"
# dependencies = ["g2b-compare"]
# ///
# How to run: uv run tools/capture_g2b_contracts.py --secret-source PATH

"""Run durable G2B contract capture from a secret source path."""

from g2b_compare.contracts.live import main

raise SystemExit(main())
