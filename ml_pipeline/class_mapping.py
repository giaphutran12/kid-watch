"""
Class mapping for KID-WATCH activity recognition.

Maps Kinetics-700 action classes to our 3 target classes:
- studying: reading_book, reading_newspaper, writing
- sleeping: sleeping, yawning
- other: catch-all for non-study, non-sleep activities
"""

# Kinetics-700 subdirectory name → our target class
CLASS_MAPPING = {
    "reading_book": "studying",
    "reading_newspaper": "studying",
    "writing": "studying",
    "sleeping": "sleeping",
    "yawning": "sleeping",
    "other": "other",
}

# Ordered list of our target classes
CLASS_NAMES = ["studying", "sleeping", "other"]

# Class name → integer index for model training
CLASS_TO_INDEX = {name: idx for idx, name in enumerate(CLASS_NAMES)}

# Reverse: index → class name
INDEX_TO_CLASS = {idx: name for name, idx in CLASS_TO_INDEX.items()}
