export function escapeHtml(text: string): string {
  // SECURITY FIX (M2): escape " and ' too. Even though current code paths
  // don't put user content into attributes, this prevents future XSS regressions.
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// FIX P38: placeholder-based formatter to ensure inline code / code blocks
// are not re-processed by subsequent bold/italic passes.
//
// FIX R4: use a long random-looking placeholder string that's effectively
// impossible for user input to contain. Previously used \u0001CB\u0001 which
// theoretically could be sent by a malicious client. The new placeholder uses
// a 32-char random hex prefix generated once per Worker cold start, making
// collision astronomically unlikely.
//
// FIX TEST-2: \x00 in RegExp was unreliable across JS engines. Switched to
// split/join for restoration, which is simpler and avoids RegExp edge cases.

const PLACEHOLDER_NONCE = Math.random().toString(36).slice(2, 10) + Math.random().toString(36).slice(2, 10);
const CODE_BLOCK_PREFIX = `__CB_${PLACEHOLDER_NONCE}__`;
const CODE_BLOCK_SUFFIX = `__CBE_${PLACEHOLDER_NONCE}__`;
const CODE_SPAN_PREFIX = `__CS_${PLACEHOLDER_NONCE}__`;
const CODE_SPAN_SUFFIX = `__CSE_${PLACEHOLDER_NONCE}__`;

export function formatTelegramHtml(text: string): string {
  let html = escapeHtml(text);

  // Step 1: extract fenced code blocks ```...``` into placeholders.
  const codeBlocks: string[] = [];
  html = html.replace(/```([\s\S]*?)```/g, (_match, code: string) => {
    const idx = codeBlocks.length;
    codeBlocks.push(`<pre>${code.trim()}</pre>`);
    return `${CODE_BLOCK_PREFIX}${idx}${CODE_BLOCK_SUFFIX}`;
  });

  // Step 2: extract inline code `...` into placeholders.
  const codeSpans: string[] = [];
  html = html.replace(/`([^`\n]+?)`/g, (_match, code: string) => {
    const idx = codeSpans.length;
    codeSpans.push(`<code>${code}</code>`);
    return `${CODE_SPAN_PREFIX}${idx}${CODE_SPAN_SUFFIX}`;
  });

  // Step 3: bold transformation on the remaining text. Placeholders use
  // underscore + nonce format that won't be matched by the ** regex.
  html = html.replace(/\*\*([^\n]+?)\*\*/g, (_match, value: string) => `<b>${value}</b>`);

  // Step 4: restore code spans using split/join (avoids RegExp \x00 issues).
  // Process from highest index to lowest to avoid index shift during replacement.
  for (let i = codeSpans.length - 1; i >= 0; i--) {
    const placeholder = `${CODE_SPAN_PREFIX}${i}${CODE_SPAN_SUFFIX}`;
    html = html.split(placeholder).join(codeSpans[i]);
  }

  // Step 5: restore code blocks.
  for (let i = codeBlocks.length - 1; i >= 0; i--) {
    const placeholder = `${CODE_BLOCK_PREFIX}${i}${CODE_BLOCK_SUFFIX}`;
    html = html.split(placeholder).join(codeBlocks[i]);
  }

  return html;
}
