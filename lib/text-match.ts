/**
 * Whole-term keyword matching shared by scoring, tailoring and refinement.
 * Port of the original's text_match.py: Han/Kana/Hangul may adjoin Latin
 * skills without whitespace (so they form boundaries for adjacent terms);
 * other word characters keep boundaries so "python" ≠ "pythonic" and
 * "java" ≠ "javascript".
 */

const CJK_CHAR_CLASS =
  "[ᄀ-ᇿ぀-ヿ㄰-㆏ㇰ-ㇿ㐀-鿿ꥠ-꥿가-퟿豈-﫿ｦ-ￜ\u{1b000}-\u{1b16f}\u{20000}-\u{3ffff}]";
const CJK_RE = new RegExp(CJK_CHAR_CLASS, "u");

export function keywordInText(keyword: string, text: string): boolean {
  const normalizedKeyword = keyword.trim().toLowerCase();
  if (!normalizedKeyword) return false;
  const normalizedText = text.toLowerCase();
  if (CJK_RE.test(normalizedKeyword)) {
    return normalizedText.includes(normalizedKeyword);
  }
  const escaped = normalizedKeyword.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const pattern = new RegExp(
    `(?:(?<!\\w)|(?<=${CJK_CHAR_CLASS}))${escaped}(?:(?!\\w)|(?=${CJK_CHAR_CLASS}))`,
    "u",
  );
  return pattern.test(normalizedText);
}

export function normalizeSkillKey(skill: string): string {
  return skill.trim().replace(/\s+/g, " ").toLowerCase();
}
