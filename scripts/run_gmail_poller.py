"""Standalone CLI runner for the Gmail CS Inbox poller service.

Continuously monitors or performs single-sweep polls against the NovaCRM
Customer Success Gmail inbox (e.g. rhuthvik8@gmail.com) for inbound AE
deal notifications. Supports mock injection, tier overrides, and graceful
daemon lifecycle management.
"""

import argparse
import logging
from pathlib import Path
import sys

# Ensure UTF-8 stdout encoding on Windows systems to support status emojis
sys.stdout.reconfigure(encoding="utf-8")

# Register project root in sys.path to allow absolute imports from src
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.config import settings
from src.services.gmail_poller import GmailPoller


def main() -> None:
    """Coordinates command-line parsing, simulation injection, and poller execution.

    Execution Branches:
        1. CLI Argument Parsing & Dynamic Tier Override:
           Captures flags (--once, --interval, --filter, --mock, --tier) and applies
           runtime overrides to `settings.voice_ai_simulated_tier`.
        2. Simulated Deal Injection:
           If `--mock` is set, constructs and injects a tier-appropriate mock AE email
           (Apex Dynamics for Enterprise or Beacon Logistics for Growth) into the poller queue.
        3. Authentication Safety Interception:
           If live mode is requested without `GMAIL_APP_PASSWORD` in `.env`, warns the user
           with setup instructions and safely falls back to mock execution.
        4. Single-Sweep Polling Mode (--once):
           Executes a single check across the inbox, prints a structured summary table,
           and exits immediately without blocking.
        5. Continuous Background Daemon Mode:
           Enters an infinite polling loop running at the specified cadence until
           interrupted via Ctrl+C, releasing sockets on shutdown.
    """
    parser = argparse.ArgumentParser(
        description="NovaCRM Gmail CS Inbox Poller Service - Background Ingestion Daemon"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single poll check over pending emails and exit immediately.",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=None,
        help="Polling interval in seconds (defaults to GMAIL_POLL_INTERVAL from .env).",
    )
    parser.add_argument(
        "--filter",
        type=str,
        default=None,
        help="Subject line search keyword (defaults to '[New Deal]').",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Run with simulated in-memory email injection (offline demonstration mode).",
    )
    parser.add_argument(
        "--tier",
        type=str,
        choices=["enterprise", "growth", "ENTERPRISE", "GROWTH"],
        default=None,
        help="Override simulated plan tier: ENTERPRISE or GROWTH (defaults to .env setting).",
    )
    args = parser.parse_args()

    # Branch 1: Dynamic Tier Override Configuration
    if args.tier:
        settings.voice_ai_simulated_tier = args.tier.upper()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    print("=" * 80)
    print("  NOVACRM CS INBOX GMAIL LISTENER SERVICE  ")
    print(f"  CS Inbox Target : {settings.gmail_user}")
    print(f"  Rocketlane Owner: {settings.rocketlane_owner_email}")
    print(f"  Simulated Tier  : {settings.voice_ai_simulated_tier.upper()}")
    print("=" * 80)

    # Initialize Poller with CLI Configuration
    poller = GmailPoller(
        poll_interval=args.interval,
        subject_filter=args.filter,
        mock_mode=args.mock,
    )

    # Branch 2: Mock Ingestion Injection
    if args.mock:
        print("\n[*] Injecting sample deal email into simulated inbox queue...")
        is_grw = settings.voice_ai_simulated_tier.upper() == "GROWTH"
        mock_customer = "Beacon Logistics" if is_grw else "Apex Dynamics"
        mock_email = "ops@beaconlogistics.io" if is_grw else "alex.mercer@apexdynamics.com"
        mock_ae = "Elena Rostova" if is_grw else "Marcus Vance"
        mock_tier_label = "Growth" if is_grw else "Enterprise"

        poller.inject_mock_email(
            sender=f"{mock_ae} <{mock_ae.lower().replace(' ', '.')}@novacrm.com>",
            subject=f"[New Deal] {mock_customer} {mock_tier_label} Onboarding",
            body=(
                "Hi CS Team,\n\n"
                f"Excited to announce we just closed a new {mock_tier_label} deal!\n\n"
                f"Customer Name: {mock_customer}\n"
                f"Customer Contact Email: {mock_email}\n"
                f"AE Name: {mock_ae}\n"
                "AE Phone: +1-555-0199\n"
                "Salesforce Opportunity: https://novacrm.lightning.force.com/lightning/r/Opportunity/0068c0000/view\n\n"
                f"Thanks,\n{mock_ae.split()[0]}"
            ),
        )

    # Branch 3: Authentication Safety Interception
    if not poller.mock_mode and not poller.password:
        print("\n[!] WARNING: GMAIL_APP_PASSWORD is not set in your .env file.")
        print("    To listen to your live Gmail inbox (rhuthvik8@gmail.com):")
        print("    1. Go to your Google Account (https://myaccount.google.com/security)")
        print("    2. Enable 2-Step Verification if not already enabled.")
        print("    3. Search for 'App passwords' -> Create a new App Password named 'NovaCRM Onboarding'.")
        print("    4. Paste the 16-character password into .env: GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx")
        print("    5. Re-run this script to start live inbox monitoring.\n")
        print("[*] Running in mock/dry-run mode for this execution...")
        poller.mock_mode = True

    # Branch 4 vs 5: Execution Mode Dispatch
    if args.once:
        print("\n[*] Checking for pending deal emails (single poll)...")
        results = poller.process_incoming_deals()
        print(f"[+] Completed single poll. Deals processed: {len(results)}")
        for r in results:
            print(
                f"    - Customer: {r['customer_name']} | "
                f"Agent 1: {r['agent1_status']} | "
                f"Agent 2: {r['agent2_status']} | "
                f"Rocketlane Proj: {r['rocketlane_project_id']}"
            )
    else:
        print(f"\n[*] Starting continuous background listener (polling every {poller.poll_interval}s)...")
        print("    Press Ctrl+C to terminate the listener.\n")
        poller.start_polling()


if __name__ == "__main__":
    main()
