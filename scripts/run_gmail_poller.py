# Standalone CLI runner to start the Gmail CS Inbox poller service for NovaCRM onboarding.  # What: Module header; Why: Command-line entry point for email listener.
import argparse  # What: Import argparse; Why: Parses command line flags and options.
import logging  # What: Import standard logging; Why: Configures terminal logging levels and formats.
from pathlib import Path  # What: Import Path; Why: Resolves workspace paths cleanly.
import sys  # What: Import sys; Why: Reconfigures stdout encoding and modifies sys.path.
sys.stdout.reconfigure(encoding='utf-8')  # What: Reconfigure stdout to UTF-8; Why: Prevents cp1252 Windows encoding exceptions.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # What: Add project root to sys.path; Why: Enables src module imports.
from src.core.config import settings  # What: Import settings; Why: Retrieves configured Gmail credentials and defaults.
from src.services.gmail_poller import GmailPoller  # What: Import GmailPoller; Why: Core polling engine.


def main() -> None:  # What: Main CLI entry function; Why: Coordinates argument parsing and poller execution.
    """CLI runner for the Gmail CS inbox listener."""  # What: Docstring; Why: Explains entry point.
    parser = argparse.ArgumentParser(description="NovaCRM Gmail CS Inbox Poller Service")  # What: Create argument parser; Why: CLI interface.
    parser.add_argument("--once", action="store_true", help="Run a single poll check and exit")  # What: Once flag; Why: Non-daemon mode.
    parser.add_argument("--interval", type=int, default=None, help="Polling interval in seconds")  # What: Interval option; Why: Override poll cadence.
    parser.add_argument("--filter", type=str, default=None, help="Subject line filter keyword")  # What: Filter option; Why: Override subject keyword.
    parser.add_argument("--mock", action="store_true", help="Run with simulated mock email injection")  # What: Mock flag; Why: Offline demonstration mode.
    parser.add_argument("--tier", type=str, choices=["enterprise", "growth", "ENTERPRISE", "GROWTH"], default=None, help="Override simulated plan tier: ENTERPRISE or GROWTH (defaults to .env setting)")  # What: Tier argument; Why: Single-point override for simulation tier.
    args = parser.parse_args()  # What: Parse CLI arguments; Why: Accesses user options.

    if args.tier:  # What: Check if tier override was passed; Why: Allows CLI flag to override .env default.
        settings.voice_ai_simulated_tier = args.tier.upper()  # What: Assign simulated tier setting; Why: Dynamically switches VoiceAIClient simulation.

    logging.basicConfig(  # What: Configure logging format; Why: Clean terminal logs.
        level=logging.INFO,  # What: Info log level; Why: Visible progress logs.
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"  # What: Log format; Why: Includes time, level, and message.
    )  # What: End of logging configuration; Why: Logging ready.

    print("=" * 80)  # What: Print separator line; Why: Visual framing.
    print("  NOVACRM CS INBOX GMAIL LISTENER SERVICE  ")  # What: Print header; Why: Identifies service.
    print(f"  CS Inbox Target : {settings.gmail_user}")  # What: Print target inbox; Why: rhuthvik8@gmail.com.
    print(f"  Rocketlane Owner: {settings.rocketlane_owner_email}")  # What: Print project owner; Why: rd3377@nyu.edu.
    print(f"  Simulated Tier  : {settings.voice_ai_simulated_tier.upper()}")  # What: Print active simulated tier; Why: Shows whether Enterprise or Growth is assumed.
    print("=" * 80)  # What: Print separator line; Why: Visual framing.

    poller = GmailPoller(  # What: Instantiate GmailPoller; Why: Configures poller from CLI args.
        poll_interval=args.interval,  # What: Interval override; Why: Cadence.
        subject_filter=args.filter,  # What: Filter override; Why: Subject keyword.
        mock_mode=args.mock  # What: Mock mode flag; Why: Offline simulation.
    )  # What: End of poller instantiation; Why: Poller instance ready.

    if args.mock:  # What: Check if mock flag is set; Why: Injects sample test email.
        print("\n[*] Injecting sample deal email into simulated inbox queue...")  # What: Print injection note; Why: Terminal visibility.
        is_grw = settings.voice_ai_simulated_tier.upper() == "GROWTH"  # What: Check if simulated tier is Growth; Why: Toggles sample content.
        mock_customer = "Beacon Logistics" if is_grw else "Apex Dynamics"  # What: Customer company name; Why: Tier-appropriate name.
        mock_email = "ops@beaconlogistics.io" if is_grw else "alex.mercer@apexdynamics.com"  # What: Customer contact email; Why: Collaborator address.
        mock_ae = "Elena Rostova" if is_grw else "Marcus Vance"  # What: AE name; Why: Deal owner.
        mock_tier_label = "Growth" if is_grw else "Enterprise"  # What: Tier label string; Why: Subject line clarity.

        poller.inject_mock_email(  # What: Inject mock email; Why: Demonstrates end-to-end parsing and execution.
            sender=f"{mock_ae} <{mock_ae.lower().replace(' ', '.')}@novacrm.com>",  # What: Sample AE sender; Why: Deal owner.
            subject=f"[New Deal] {mock_customer} {mock_tier_label} Onboarding",  # What: Subject matching filter; Why: Passes filter.
            body=(  # What: Sample AE email body; Why: Standard deal notification format.
                "Hi CS Team,\n\n"  # What: Salutation; Why: Context.
                f"Excited to announce we just closed a new {mock_tier_label} deal!\n\n"  # What: Announcement; Why: Context.
                f"Customer Name: {mock_customer}\n"  # What: Customer name; Why: Project title.
                f"Customer Contact Email: {mock_email}\n"  # What: Contact email; Why: Primary collaborator.
                f"AE Name: {mock_ae}\n"  # What: AE name; Why: Deal owner.
                "AE Phone: +1-555-0199\n"  # What: AE phone; Why: Destination for Voice AI call.
                "Salesforce Opportunity: https://novacrm.lightning.force.com/lightning/r/Opportunity/0068c0000/view\n\n"  # What: SFDC link; Why: Context link.
                f"Thanks,\n{mock_ae.split()[0]}"  # What: Closing; Why: Sign-off.
            )  # What: End of body string; Why: Complete mock email.
        )  # What: End of mock injection; Why: Ready for processing.

    if not poller.mock_mode and not poller.password:  # What: Check if App Password is missing in live mode; Why: Guides user on setup.
        print("\n[!] WARNING: GMAIL_APP_PASSWORD is not set in your .env file.")  # What: Print warning; Why: Alerts user.
        print("    To listen to your live Gmail inbox (rhuthvik8@gmail.com):")  # What: Print instructions step 1; Why: Setup guidance.
        print("    1. Go to your Google Account (https://myaccount.google.com/security)")  # What: Print URL; Why: Security page.
        print("    2. Enable 2-Step Verification if not already enabled.")  # What: Print 2FA requirement; Why: Required for App Passwords.
        print("    3. Search for 'App passwords' -> Create a new App Password named 'NovaCRM Onboarding'.")  # What: Print password creation; Why: Token generation.
        print("    4. Paste the 16-character password into .env: GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx")  # What: Print .env update; Why: Configuration.
        print("    5. Re-run this script to start live inbox monitoring.\n")  # What: Print next step; Why: Run instruction.
        print("[*] Running in mock/dry-run mode for this execution...")  # What: Print fallback; Why: Runs offline.
        poller.mock_mode = True  # What: Fallback to mock mode; Why: Allows script to execute safely without crashing.

    if args.once:  # What: Check if once flag was passed; Why: Executes single check.
        print("\n[*] Checking for pending deal emails (single poll)...")  # What: Print progress; Why: Single poll note.
        results = poller.process_incoming_deals()  # What: Process pending deals once; Why: Ingests available emails.
        print(f"[+] Completed single poll. Deals processed: {len(results)}")  # What: Print completion; Why: Summary.
        for r in results:  # What: Loop over results; Why: Displays each processed deal.
            print(f"    - Customer: {r['customer_name']} | Agent 1: {r['agent1_status']} | Agent 2: {r['agent2_status']} | Rocketlane Proj: {r['rocketlane_project_id']}")  # What: Summary line; Why: Readable outcome.
    else:  # What: Daemon mode branch; Why: Continuously polls inbox.
        print(f"\n[*] Starting continuous background listener (polling every {poller.poll_interval}s)...")  # What: Print start message; Why: Terminal visibility.
        print("    Press Ctrl+C to terminate the listener.\n")  # What: Print exit instruction; Why: User guidance.
        poller.start_polling()  # What: Start continuous polling; Why: Listens for incoming emails.


if __name__ == "__main__":  # What: Entry point check; Why: Runs main when script executed directly.
    main()  # What: Execute main function; Why: Starts poller CLI.
