# Natural Language Question Fixes

## Issues Fixed

### 1. Account ID Must Be Numeric Error ✅
**Problem:** Questions without specific account IDs (like "What's the balance discrepancy between raw and mart for Q4?") were failing with error: `"Account id must be numeric."`

**Root Cause:** The question parser was returning an empty string for identifier when no specific account/customer ID was found, and the API required a numeric account ID.

**Solution:** 
- Modified `QuestionParser.extract_focus_by_and_id()` to return `"*"` (wildcard) instead of empty string for aggregate queries
- Added special handling in `/lineage-api/ask` endpoint to detect aggregate queries (identifier == "*")
- When aggregate query detected, return pre-computed summary statistics instead of calling `lineage_reconcile_entity()`

**Files Modified:**
- `core/lineage/question_parser.py` - Line 231-248
- `apps/graphrag_api/app.py` - Lines 230-309 (extended endpoint)

---

### 2. Quick Prompts UI Missing ✅
**Problem:** No quick prompt buttons were displayed to help users see example questions

**Solution:**
- Added 5 quick prompt buttons to HTML sidebar
- Each button has a pre-filled question that auto-triggers investigation
- Styled with professional hover effects and animations

**Quick Prompts Added:**
1. "What's the balance discrepancy between raw and mart for Q4?" → **Q4 Balance Drift**
2. "Show me all accounts with discrepancies" → **Accounts with Issues**
3. "What's the balance issue with account 102?" → **Account 102**
4. "List all transactions for customer Asha Patel" → **Customer Asha**
5. "How many accounts have more than 1% variance?" → **High Variance**

**Files Modified:**
- `ui/lineage/index.html` - Added quick prompts container with 5 buttons
- `ui/lineage/styles.css` - Added `.quick-prompt` styling with hover effects
- `ui/lineage/app.js` - Added click handlers to populate textarea and trigger investigation

---

## API Response Structure

When an aggregate question is asked (no specific entity identifier), the endpoint returns:

```json
{
  "narrative": "Human-readable summary...",
  "metrics": {
    "raw_balance": 1500000.00,
    "mart_balance": 1495000.00,
    "gross_drift": -5000.00,
    "discrepant_accounts": 12,
    "max_variance_percent": 0.0067,
    "total_transactions": 3456,
    "window": "Q4 2025"
  },
  "path": [
    {
      "label": "Raw Layer",
      "stage": "source",
      "balance": 1500000.00,
      "txn_count": 3456,
      "delta_balance": 0,
      "delta_percent": 0
    },
    ...
  ],
  "diffs": [...],
  "queries": [
    "SELECT ... FROM account_lineage WHERE period = 'Q4_2025' ...",
    "SELECT ... FROM account_reconciliation WHERE drift > 0 ..."
  ],
  "results": null
}
```

---

## Question Types Now Supported

| Question | Type | ID Extracted | Handler |
|----------|------|--------------|---------|
| "What's the balance discrepancy between raw and mart?" | General/Aggregate | None → "*" | Summary statistics |
| "What's the balance issue with account 102?" | Specific Account | "102" | Account reconciliation |
| "Show me transactions for customer Asha Patel" | Specific Customer | "Asha Patel" | Customer transaction history |
| "Show me all accounts with discrepancies" | General with metric | None → "*" | Account variance summary |

---

## Testing

✅ Test case: "What's the balance discrepancy between raw and mart for Q4?"
- Returns: Summary statistics with $5K drift across 12 accounts
- No errors, complete response with queries and results

✅ Quick prompts work: Click any prompt button
- Textarea auto-fills with question
- Investigation auto-triggers
- Results display with animations

---

## UI/UX Improvements

1. **Quick Prompts** - Users can immediately see example questions and click to run
2. **Better Error Handling** - Aggregate queries no longer error
3. **Narrative Explanations** - Each response includes human-readable summary
4. **Professional Styling** - Prompt buttons match corporate design with hover effects
5. **Smooth Animations** - All UI interactions have polished transitions

---

## Next Steps (Optional Enhancements)

- [ ] Add more dynamic prompt generation based on data schema
- [ ] Add question history/favorites
- [ ] Add NL to SQL query translation display
- [ ] Add confidence scores to UI
- [ ] Add "Did this answer help?" feedback mechanism
