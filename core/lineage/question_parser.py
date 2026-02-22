# core/lineage/question_parser.py
"""
Smart Question Parser for Natural Language Lineage Investigations

Parses user questions to extract:
- Investigation type (account, customer, transaction, balance, position, deposit)
- Entity identifiers (IDs, names)
- Focus metrics (balance, count, transactions, etc.)
- Date ranges (optional)
"""

import re
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
from enum import Enum

class InvestigationType(Enum):
    """Supported investigation types based on semantic.yaml entities"""
    ACCOUNT = "account"           # accounts.account_id
    CUSTOMER = "customer"         # customers.customer_id
    TRANSACTION = "transaction"   # transactions.txn_id
    DEPOSIT = "deposit"           # time_deposits.deposit_id
    POSITION = "position"         # securities_positions.position_id
    GENERAL = "general"           # Fallback for complex queries


class FocusMetric(Enum):
    """Focus metrics for investigation"""
    BALANCE = "balance"           # Account/customer balance
    TRANSACTIONS = "transactions" # Transaction history
    INFLOWS = "inflows"          # Deposits/income
    OUTFLOWS = "outflows"        # Withdrawals/expenses
    FEES = "fees"                # Fee charges
    COUNT = "count"              # Row counts
    DISCREPANCIES = "discrepancies"  # Variances
    ALL = "all"                  # Default: all metrics


@dataclass
class ParsedQuestion:
    """Structured representation of user question"""
    original_question: str
    investigation_type: InvestigationType
    focus_metric: FocusMetric
    identifiers: List[str]          # Account IDs, customer names, txn IDs, etc.
    date_range: Optional[tuple]     # (start_date, end_date) if specified
    confidence: float               # 0.0-1.0 parsing confidence
    suggested_query: str            # Human-readable query summary
    raw_intent: str                # Parsed intent in structured form
    ranking: Optional[str] = None  # "highest" | "lowest" when superlative intent is detected


class QuestionParser:
    """Parse natural language questions into structured investigation requests"""
    
    # Synonym mappings based on semantic.yaml
    ENTITY_SYNONYMS = {
        'account': ['account', 'acct', 'bank account', 'portfolio', 'checking', 'savings', 'brokerage'],
        'customer': ['customer', 'client', 'user', 'person', 'holder', 'account holder', 'patron'],
        'transaction': ['transaction', 'txn', 'transfer', 'posting', 'charge', 'deposit', 'withdrawal'],
        'deposit': ['deposit', 'cd', 'certificate of deposit', 'fixed deposit', 'time deposit'],
        'position': ['position', 'holding', 'portfolio line', 'security', 'stock', 'bond', 'etf', 'fund'],
    }
    
    METRIC_SYNONYMS = {
        'balance': ['balance', 'balances', 'cash', 'funds', 'available balance', 'available balances', 'account balance', 'account balances', 'total balance', 'total balances'],
        'transactions': ['transaction', 'txn', 'transfer', 'activity', 'history', 'movement'],
        'inflows': ['inflow', 'deposit', 'income', 'incoming', 'deposit', 'received'],
        'outflows': ['outflow', 'withdrawal', 'expense', 'outgoing', 'spent', 'paid'],
        'fees': ['fee', 'charges', 'cost', 'commission', 'penalty'],
        'count': ['count', 'number', 'how many', 'total count'],
        'discrepancies': ['discrepancy', 'variance', 'difference', 'mismatch', 'delta', 'gap'],
    }
    
    def __init__(self):
        self.entity_patterns = self._build_entity_patterns()
        self.metric_patterns = self._build_metric_patterns()
    
    def _build_entity_patterns(self) -> Dict[str, str]:
        """Build regex patterns for entity detection"""
        patterns = {}
        for entity, synonyms in self.ENTITY_SYNONYMS.items():
            # Combine synonyms into regex pattern
            syn_pattern = '|'.join(f'\\b{s}\\b' for s in synonyms)
            patterns[entity] = syn_pattern
        return patterns
    
    def _build_metric_patterns(self) -> Dict[str, str]:
        """Build regex patterns for metric detection"""
        patterns = {}
        for metric, synonyms in self.METRIC_SYNONYMS.items():
            syn_pattern = '|'.join(f'\\b{s}\\b' for s in synonyms)
            patterns[metric] = syn_pattern
        return patterns
    
    def parse(self, question: str) -> ParsedQuestion:
        """Parse natural language question into structured investigation"""
        question_lower = question.lower().strip()
        confidence = 0.7  # Start with reasonable baseline
        
        # 1. Detect investigation type
        inv_type, type_conf = self._detect_investigation_type(question_lower)
        confidence = (confidence + type_conf) / 2
        
        # 2. Detect focus metric
        metric, metric_conf = self._detect_focus_metric(question_lower)
        confidence = (confidence + metric_conf) / 2
        
        # 3. Extract identifiers (account IDs, customer names, etc.)
        identifiers = self._extract_identifiers(question_lower)
        if identifiers:
            confidence = min(1.0, confidence + 0.15)
        
        # 4. Extract date range if present
        date_range = self._extract_date_range(question_lower)
        if date_range:
            confidence = min(1.0, confidence + 0.1)
        
        # 5. Build suggested query
        ranking = self._detect_ranking(question_lower)
        suggested_query = self._build_suggested_query(inv_type, metric, identifiers, date_range, ranking)
        
        # 6. Create raw intent string
        raw_intent = f"{inv_type.value}:{metric.value}"
        if ranking:
            raw_intent += f":{ranking}"
        if identifiers:
            raw_intent += f":{','.join(identifiers)}"
        
        return ParsedQuestion(
            original_question=question,
            investigation_type=inv_type,
            focus_metric=metric,
            identifiers=identifiers,
            date_range=date_range,
            confidence=min(1.0, confidence),
            suggested_query=suggested_query,
            raw_intent=raw_intent,
            ranking=ranking,
        )

    def _detect_ranking(self, question: str) -> Optional[str]:
        """Detect superlative/ranking intent from NL question."""
        if re.search(r'\b(highest|top|largest|max(?:imum)?)\b', question, re.IGNORECASE):
            return "highest"
        if re.search(r'\b(lowest|bottom|smallest|min(?:imum)?)\b', question, re.IGNORECASE):
            return "lowest"
        return None
    
    def _detect_investigation_type(self, question: str) -> tuple[InvestigationType, float]:
        """Detect which entity the question is about"""
        scores = {}
        
        for entity_type, pattern in self.entity_patterns.items():
            matches = len(re.findall(pattern, question, re.IGNORECASE))
            if matches > 0:
                scores[entity_type] = matches
        
        if not scores:
            return InvestigationType.GENERAL, 0.3
        
        # Rank by frequency of mentions
        best_entity = max(scores.items(), key=lambda x: x[1])
        conf = min(1.0, best_entity[1] * 0.3)  # More mentions = higher confidence
        
        entity_map = {
            'account': InvestigationType.ACCOUNT,
            'customer': InvestigationType.CUSTOMER,
            'transaction': InvestigationType.TRANSACTION,
            'deposit': InvestigationType.DEPOSIT,
            'position': InvestigationType.POSITION,
        }
        
        return entity_map.get(best_entity[0], InvestigationType.GENERAL), conf
    
    def _detect_focus_metric(self, question: str) -> tuple[FocusMetric, float]:
        """Detect which metric user is interested in"""
        scores = {}
        
        for metric, pattern in self.metric_patterns.items():
            matches = len(re.findall(pattern, question, re.IGNORECASE))
            if matches > 0:
                scores[metric] = matches
        
        if not scores:
            return FocusMetric.ALL, 0.5
        
        best_metric = max(scores.items(), key=lambda x: x[1])
        conf = min(1.0, best_metric[1] * 0.4)
        
        metric_map = {
            'balance': FocusMetric.BALANCE,
            'transactions': FocusMetric.TRANSACTIONS,
            'inflows': FocusMetric.INFLOWS,
            'outflows': FocusMetric.OUTFLOWS,
            'fees': FocusMetric.FEES,
            'count': FocusMetric.COUNT,
            'discrepancies': FocusMetric.DISCREPANCIES,
        }
        
        return metric_map.get(best_metric[0], FocusMetric.ALL), conf
    
    def _extract_identifiers(self, question: str) -> List[str]:
        """Extract account IDs, customer names, transaction IDs, etc."""
        identifiers = []
        
        # Pattern 1: Account IDs (numbers)
        account_ids = re.findall(r'\baccount\s+(?:id\s+)?(\d+)\b', question, re.IGNORECASE)
        identifiers.extend(account_ids)
        
        # Pattern 2: Customer IDs/names
        customer_matches = re.findall(r'\bcustomer\s+(?:id\s+)?([A-Za-z0-9\s]+?)(?:\.|,|\s+(?:has|with|for|on)|\s*$)', question, re.IGNORECASE)
        identifiers.extend([m.strip() for m in customer_matches if m.strip()])
        
        # Pattern 3: Transaction IDs
        txn_ids = re.findall(r'\btxn\s+(?:id\s+)?(\d+)\b', question, re.IGNORECASE)
        identifiers.extend(txn_ids)
        
        # Pattern 4: Named entities (quoted strings or proper nouns)
        quoted = re.findall(r'["\']([^"\']+)["\']', question)
        identifiers.extend(quoted)
        
        # Pattern 5: Potential customer names (capitalized words after key phrases)
        name_context = re.findall(r'(?:for|of|belongs to)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)', question)
        identifiers.extend(name_context)
        
        return list(set(identifiers))  # Remove duplicates
    
    def _extract_date_range(self, question: str) -> Optional[tuple]:
        """Extract date range if present (returns (start, end) or None)"""
        # Look for date patterns like "2024-01-01", "January 2024", "last 30 days", etc.
        
        # Pattern: YYYY-MM-DD or MM/DD/YYYY
        date_pattern = r'\b(\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4})\b'
        dates = re.findall(date_pattern, question)
        
        if len(dates) >= 2:
            return (dates[0], dates[1])
        elif len(dates) == 1:
            return (dates[0], None)
        
        # Pattern: "last N days/months"
        last_n = re.search(r'last\s+(\d+)\s+(day|month|quarter|year)', question, re.IGNORECASE)
        if last_n:
            return ("last_" + last_n.group(1) + last_n.group(2)[0], None)
        
        return None
    
    def _build_suggested_query(self, inv_type: InvestigationType, metric: FocusMetric,
                               identifiers: List[str], date_range: Optional[tuple],
                               ranking: Optional[str]) -> str:
        """Build human-readable query summary"""
        parts = []
        
        # Query intent
        if ranking and metric != FocusMetric.ALL:
            parts.append(f"Find {ranking} {metric.value} for {inv_type.value}")
        elif ranking and metric == FocusMetric.ALL:
            parts.append(f"Find {ranking} values for {inv_type.value}")
        elif metric == FocusMetric.ALL:
            parts.append(f"Investigate all metrics for {inv_type.value}")
        else:
            parts.append(f"Check {metric.value} for {inv_type.value}")
        
        # Identifiers
        if identifiers:
            if len(identifiers) == 1:
                parts.append(f" '{identifiers[0]}'")
            else:
                parts.append(f" ({', '.join(identifiers[:3])}{'...' if len(identifiers) > 3 else ''})")
        
        # Date range
        if date_range:
            if date_range[1]:
                parts.append(f" from {date_range[0]} to {date_range[1]}")
            else:
                parts.append(f" since {date_range[0]}")
        
        return "".join(parts)
    
    def extract_focus_by_and_id(self, parsed: ParsedQuestion) -> tuple[str, str]:
        """Convert parsed question to focusBy and identifier for API"""
        # Map investigation type to focusBy parameter
        if parsed.investigation_type in [InvestigationType.CUSTOMER]:
            focus_by = "customer"
        elif parsed.investigation_type in [InvestigationType.ACCOUNT, InvestigationType.GENERAL]:
            focus_by = "account"
        else:
            focus_by = parsed.investigation_type.value
        
        # Use first identifier, or use wildcard for aggregate questions
        if parsed.identifiers:
            identifier = parsed.identifiers[0]
        else:
            # For general/aggregate questions, use wildcard
            # This allows querying summary statistics without a specific account
            identifier = "*"  # Signals aggregate query
        
        return focus_by, identifier
