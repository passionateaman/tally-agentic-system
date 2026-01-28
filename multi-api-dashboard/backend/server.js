import express from 'express';
import cors from 'cors';
import dotenv from 'dotenv';
import fetch from 'node-fetch';

dotenv.config();

const app = express();
app.use(cors());
app.use(express.json({ limit: '2mb' }));

const GEMINI_API_KEY = process.env.GEMINI_API_KEY;
if (!GEMINI_API_KEY) {
  console.error('❌ GEMINI_API_KEY missing');
  process.exit(1);
}

const MODEL_NAME = 'gemini-1.5-pro';

// 🔹 simple deterministic fallback
const fallbackScore = (query, answer) => {
  const q = query.toLowerCase().split(/\W+/);
  const a = answer.toLowerCase().split(/\W+/);
  const common = q.filter(w => a.includes(w));
  const ratio = common.length / Math.max(q.length, 1);
  return Math.min(100, Math.max(30, Math.round(ratio * 100)));
};

app.post('/relevancy', async (req, res) => {
  const { query, answer } = req.body;

  if (!query || !answer) {
    return res.status(400).json({ score: 0 });
  }

  let answerText = '';
  try {
    answerText =
      typeof answer === 'string'
        ? answer.slice(0, 3000)
        : JSON.stringify(answer, null, 2).slice(0, 3000);
  } catch {
    answerText = String(answer);
  }

  const prompt = `
You are an evaluator that scores the RELEVANCY of an answer to a query.

IMPORTANT CONTEXT:
- The data is TALLY FINANCIAL DATA (Balance Sheet, Profit & Loss, Cash Flow, Ledgers).
- The answer may contain financial summaries, tables, or charts/graphs (e.g., Vega-Lite).
- Output format does NOT matter.
- Graphs/tables are OPTIONAL unless the query explicitly asks for them.

SCORING RULES:
- Score between 0 and 100.
- Evaluate relevance based on FINANCIAL CORRECTNESS and QUERY INTENT.
- Give a HIGH score if:
  - The financial question is correctly answered.
  - A correct summary is present, even if only summary is returned.
  - Graphs/tables support the summary or are reasonably related.
- Give a MEDIUM score if:
  - Summary is mostly correct but generic.
  - Visualization exists but is loosely related.
- Give a LOW score if:
  - Financial values, ledgers, periods, or report types are incorrect.
  - The answer ignores the query intent.

DO NOT penalize:
- Missing graphs when the summary is correct.
- Formatting or presentation issues.
- Extra financial insights beyond the query.

STRICT OUTPUT:
Return ONLY valid JSON.
Example:
{"score": 85}

Query:
${query}

Answer:
${answerText}
`;


  let score = 0;

  try {
    const response = await fetch(
      `https://generativelanguage.googleapis.com/v1/models/${MODEL_NAME}:generateContent?key=${GEMINI_API_KEY}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          contents: [{ parts: [{ text: prompt }] }]
        })
      }
    );

    const text = await response.text();
    const data = text ? JSON.parse(text) : null;

    const rawText =
      data?.candidates?.[0]?.content?.parts?.[0]?.text || '';

    console.log('🧠 RAW GEMINI TEXT >>>', rawText);

    if (rawText) {
      const cleaned = rawText.replace(/```json|```/gi, '').trim();
      score = Number(JSON.parse(cleaned).score);
    }
  } catch (err) {
    console.error('⚠️ Gemini failed, using fallback');
  }

  // 🔹 fallback if LLM silent
  if (!score || isNaN(score)) {
    score = fallbackScore(query, answerText);
  }

  score = Math.max(0, Math.min(100, score));
  console.log('✅ FINAL SCORE:', score);

  res.json({ score });
});

app.listen(4000, () => {
  console.log('✅ Relevancy server running on http://localhost:4000');
});
