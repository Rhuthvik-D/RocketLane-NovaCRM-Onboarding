# Package initializer for multi-agent system components: Agent 1, Agent 2, and Agent 3.  # What: Module header; Why: Marks src/agents as Python package.
"""Multi-agent system modules for NovaCRM customer onboarding automation."""  # What: Docstring; Why: Describes package scope.
from src.agents.agent1_intake import Agent1Intake, agent1_intake  # What: Export Agent 1; Why: Deal intake orchestrator.
from src.agents.agent2_communication import Agent2Communication, agent2_communication  # What: Export Agent 2; Why: Communication orchestrator.
from src.agents.agent3_data_qa import Agent3DataQAGatekeeper, agent3_data_qa  # What: Export Agent 3; Why: Data QA gatekeeper orchestrator.
from src.agents.intake_parser import IntakeParser, intake_parser  # What: Export intake parser; Why: Email validation.
from src.agents.voice_guardrail import VoiceGuardrail, voice_guardrail  # What: Export voice guardrail; Why: Telephony evaluation.

__all__ = [  # What: Package exports list; Why: Restricts public interface of src.agents.
    "Agent1Intake",  # What: Agent 1 class; Why: Custom instance creation.
    "agent1_intake",  # What: Agent 1 singleton; Why: Shared instance.
    "Agent2Communication",  # What: Agent 2 class; Why: Custom instance creation.
    "agent2_communication",  # What: Agent 2 singleton; Why: Shared instance.
    "Agent3DataQAGatekeeper",  # What: Agent 3 class; Why: Custom instance creation.
    "agent3_data_qa",  # What: Agent 3 singleton; Why: Shared instance.
    "IntakeParser",  # What: IntakeParser class; Why: Validation helper.
    "intake_parser",  # What: IntakeParser singleton; Why: Shared instance.
    "VoiceGuardrail",  # What: VoiceGuardrail class; Why: Voice guardrail helper.
    "voice_guardrail",  # What: VoiceGuardrail singleton; Why: Shared instance.
]  # What: End of exports list; Why: Complete package interface.
