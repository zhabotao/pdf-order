# Balanced attention for language modelling

近年来 attention 已成为主流机制。However, the column constraint has not been studied in depth, and this remains unclear for long context models that process sequences far longer than the typical training window used in most prior work. We propose a balanced attention layer that keeps both row and column margins fixed.

The model improves perplexity by 12% on WikiText and outperforms the baseline on RULER. We train decoder-only Transformers from 160M to 7B parameters on 400B tokens with learning rate 3e-4 and batch size 64. Evaluation uses perplexity and accuracy as metrics.
