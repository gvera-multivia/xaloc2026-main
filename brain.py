#!/usr/bin/env python
import logging

from services.brain_claim.app import main as brain_claim_main


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - [BRAIN] - %(levelname)s - %(message)s")
    logging.getLogger("brain").warning(
        "brain.py legado migrado a modo microservicios. Ejecutando services.brain_claim.app (sin SQLite)."
    )
    brain_claim_main()


if __name__ == "__main__":
    main()
