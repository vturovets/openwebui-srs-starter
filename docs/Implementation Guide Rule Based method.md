# Rule‑Based Synonyms & Heuristics Implementation Guide

This guide describes how to implement a **rule‑based method** for mapping free‑text holiday preferences to structured filters and options. The approach relies on manually curated synonyms and simple heuristics to transform user input into the filter selections defined in `filters_options.csv`. It is suitable as a low‑latency baseline and a fallback when other methods fail.

## 1 Purpose and Context

In the NLP‑Powered Holiday Request prototype (see CR‑004), users can enter additional free‑text preferences in **Preferences** mode. The system must interpret these preferences and select relevant filters and options from a canonical catalogue. A rule‑based method achieves this by matching keywords or phrases against the catalogue and mapping them deterministically. Because there is no labelled training data at the outset, rules offer a transparent starting point.

Key assumptions:

- **Catalogue:** `filters_options.csv` contains all filter categories (e.g. *Facilities*, *Boards*, *Holiday Type*) and option labels (e.g. “Free Wi‑Fi”, “Room Only”, “Scuba – additional info”). It is the single source of truth (FR‑14–FR‑21 in CR‑004). Each row has a unique `filterId`, `filterLabel`, `optionId`, and `optionLabel`.

- **Language:** initial implementation covers English only; synonyms for Dutch and French can be added later.

- **Negation:** phrases like “no catering” should map to a positive equivalent (e.g. `Boards: Room Only`) rather than a negative flag (user clarification #4). Rules should detect negation and invert the mapping accordingly.

## 2 Catalogue Ingestion and Synonym Dictionary

1. **Load the catalogue:**
   
   - Read `filters_options.csv` at startup using Python’s `csv` or `pandas` module. Store each filter as an object with a `filterId`, `filterLabel`, and a list of options. Each option has an `optionId`, `optionLabel`, and optionally a list of synonyms (if provided).
   
   - Lower‑case `filterLabel` and `optionLabel` and remove punctuation to normalise them for matching. E.g. `Free Wi‑Fi` → `free wifi`.

2. **Create a synonym dictionary:**
   
   - For each option, define a set of canonical **synonyms** capturing alternative phrasings and morphological variants. For example:
     
     ```python
     synonyms = {
         "free wifi": {"wifi", "wi‑fi", "internet", "internet access", "wireless"},
         "room only": {"no catering", "without meals", "room only"},
         "scuba – additional info": {"scuba", "scuba diving", "diving facilities"}
     }
     ```
   
   - Use domain expertise to build this list. You can start with obvious synonyms and expand as you collect user inputs. Optionally implement stemming or lemmatisation to handle morphological forms (e.g. “dives” → “dive”).

3. **Build an inverted index:**
   
   - Create a mapping from each synonym to the option(s) it belongs to. For example, `"internet" → [optionId for free_wifi]`. Some synonyms may map to multiple options; record all associations and use scoring heuristics to choose among them.
   
   - Data structure: a dictionary where keys are lower‑cased synonyms and values are lists of `(filterId, optionId)` pairs.

## 3 User Text Pre‑processing

1. **Normalisation:** For each input request:
   
   - Lower‑case the text.
   
   - Remove punctuation and extra whitespace.
   
   - Optionally apply tokenisation and simple lemmatisation.

2. **Negation detection:** Identify negation cues (`no`, `not`, `without`, `don’t`, etc.) preceding or following nouns. For example, in “no catering but scuba diving facilities must be available,” the token “no” negates “catering.” When a negation is detected, map the expression to a positive alternative (e.g. “no catering” → “Room Only”). A simple approach:
   
   - Use regular expressions to detect patterns like `\b(no|not|without|don’t)\s+([\w\-]+(?:\s+\w+)*)`.
   
   - Look up the second group in the synonym dictionary. If it matches a board option (e.g. catering synonyms), choose the positive board option as the mapping.

3. **Token and n‑gram generation:** Split the pre‑processed text into unigrams and bigrams. Generate n‑grams up to length 2 or 3 to match multi‑word synonyms (e.g. “scuba diving”).

## 4 Matching and Scoring Heuristics

1. **Exact synonym matches:** For each n‑gram, check if it exists in the synonym dictionary. If found, record the candidate `(filterId, optionId)` pair and the length of the n‑gram (longer phrases get higher weight).

2. **Negation handling:** When a synonym occurs within a negated context, map it to a positive alternative (e.g. “no wifi” might map to a board option if appropriate). If no positive alternative is defined, mark the option with `selected=false` and exclude it.

3. **Scoring:** Assign a confidence score to each candidate option. Suggested factors:
   
   - **Phrase length:** bigrams/trigrams receive higher scores than unigrams.
   
   - **Multiplicity:** multiple mentions of the same option increase confidence.
   
   - **Negation penalty:** if a negation triggers an alternative mapping, reduce the score to reflect lower certainty.

4. **Option selection:** After scoring, select candidates whose score exceeds a configurable threshold (e.g. 0.5). For each filter, mark the highest‑scoring option(s) with `selected=true` and include any lower‑scoring candidates as alternatives with `selected=false` if you wish to show possible matches. If no options exceed the threshold, return `selected=false` for all options or an empty list and include a status in `metadata` (FR‑24 in CR‑004).

## 5 Structured Output Format

The response must conform to the CR‑004 specification (FR‑12). For each selected filter, include its ID and label, and for each option include `optionId`, `optionLabel`, `selected` (boolean), and a `confidence` value. Example:

```json
{
  "filters": [
    {
      "filterId": "facilities",
      "filterLabel": "Facilities",
      "options": [
        {"optionId": "free_wifi", "optionLabel": "Free Wi‑Fi", "selected": true, "confidence": 0.8},
        {"optionId": "wifi_star", "optionLabel": "Wi‑Fi*", "selected": false, "confidence": 0.4}
      ]
    },
    {
      "filterId": "boards",
      "filterLabel": "Boards",
      "options": [
        {"optionId": "room_only", "optionLabel": "Room Only", "selected": true, "confidence": 0.7}
      ]
    }
  ],
  "metadata": {
    "method": "rules",
    "mode": "preferences",
    "timings": {"totalMs": 100},
    "thresholdBreached": false
  }
}
```

## 6 Configuration and Maintenance

- **Synonym file:** Store synonyms in a separate YAML/JSON file (e.g. `synonyms.json`) with structure:
  
  ```json
  {
    "free wifi": ["wifi", "wi‑fi", "internet", "internet access"],
    "room only": ["no catering", "without meals", "room only"]
  }
  ```
  
  Load this file at startup and update it as you gather more phrases.

- **Thresholds:** Expose scoring thresholds and negation penalties via environment variables or a configuration file. This allows tuning without code changes.

- **Language extensibility:** For Dutch and French, create separate synonym dictionaries and detection patterns. Detect the input language using existing language detection in the pipeline and load the corresponding dictionary.

- **Logging:** Record the raw input, method (`rules`), processing time, selected options, and confidence scores in the CSV log (FR‑26–FR‑27). This enables benchmarking and refinement.

## 7 Limitations and Considerations

- **Coverage:** Rules can only capture preferences that have synonyms defined. Rare phrasings or metaphorical expressions may be missed.

- **Maintenance overhead:** Synonyms must be manually curated and kept up to date. As the catalogue grows, this becomes laborious.

- **False positives:** Without context, keyword matching may misinterpret phrases. For example, “I want to relax and read by the pool” matches “pool” but not necessarily “swimming pool facilities.” Test and adjust heuristics accordingly.

- **Complex grammar:** The simple negation detection may not capture complex sentences or double negatives. Additional parsing (e.g. dependency parsing) could improve accuracy.

Despite these limitations, a rule‑based system is an essential baseline: it is deterministic, interpretable, and can run with near‑zero latency. It also provides useful fallback behaviour when other methods (embeddings or LLMs) fail or return low confidence.
