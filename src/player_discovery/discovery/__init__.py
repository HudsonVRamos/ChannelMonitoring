"""Discovery Engine — Análise completa de capabilities do player."""

from .behavioral_tester import BehavioralTester, BehavioralTestResult
from .browser_api_analyzer import BrowserAPIAnalyzer, BrowserAPIEvidence
from .css_analyzer import (
    CSSAnalyzer,
    CSSEvidence,
    MAX_CSS_ONLY_CONFIDENCE,
)
from .dom_analyzer import (
    DOMAnalyzer,
    DOMEvidence,
    CAPABILITY_KEYWORDS,
    INTERACTIVE_ROLES,
)
from .engine import DiscoveryEngine
from .js_analyzer import JSAnalyzer, JSEvidence
from .mutation_watcher import (
    MutationObserverWatcher,
    classify_mutation,
    STRUCTURAL_ATTRIBUTES,
    STRUCTURAL_ATTRIBUTE_PREFIXES,
    COSMETIC_ATTRIBUTES,
)

__all__ = [
    "BehavioralTester",
    "BehavioralTestResult",
    "BrowserAPIAnalyzer",
    "BrowserAPIEvidence",
    "CSSAnalyzer",
    "CSSEvidence",
    "DiscoveryEngine",
    "MAX_CSS_ONLY_CONFIDENCE",
    "DOMAnalyzer",
    "DOMEvidence",
    "CAPABILITY_KEYWORDS",
    "INTERACTIVE_ROLES",
    "JSAnalyzer",
    "JSEvidence",
    "MutationObserverWatcher",
    "classify_mutation",
    "STRUCTURAL_ATTRIBUTES",
    "STRUCTURAL_ATTRIBUTE_PREFIXES",
    "COSMETIC_ATTRIBUTES",
]
