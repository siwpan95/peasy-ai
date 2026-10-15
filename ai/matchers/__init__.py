"""匹配器系统：可插拔的输入匹配策略。"""

from .base import BaseMatcher, MatchResult
from .regex_matcher import RegexMatcher
from .fuzzy_matcher import FuzzyMatcher
from .markov_chain import MarkovChain, MarkovMatcher
from .neural_matcher import NeuralMatcher
from .retrieval import RetrievalIndex
from .registry import MATCHER_REGISTRY, register_matcher, get_registered_matchers, discover_and_register

__all__ = [
    "BaseMatcher", "RegexMatcher", "FuzzyMatcher", "MarkovChain", "MarkovMatcher",
    "NeuralMatcher", "RetrievalIndex", "MatchResult",
    "MATCHER_REGISTRY", "register_matcher", "get_registered_matchers", "discover_and_register",
]
