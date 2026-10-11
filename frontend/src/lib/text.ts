/** Shared checks for text typed or pasted into forms (the server makes the same checks). */

export const CONTROL_MESSAGE = "Text can't contain control characters.";
export const DATE_RANGE_MESSAGE = "Dates must be between 2020 and 2100.";
export const MIN_DATE = "2020-01-01";
export const MAX_DATE = "2100-12-31";

// C0 and C1 control characters; a new line and a tab are allowed in multi-line text only.
const CONTROL = /[\u0000-\u001f\u007f-\u009f]/;
const CONTROL_EXCEPT_LINES = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f]/;

/** An error message if the text holds a control character, otherwise null. */
export function controlCharError(text: string, multiline = false): string | null {
  return (multiline ? CONTROL_EXCEPT_LINES : CONTROL).test(text) ? CONTROL_MESSAGE : null;
}

/** An error message if an ISO date ("YYYY-MM-DD") is outside 2020 to 2100, otherwise null. */
export function dateRangeError(iso: string): string | null {
  return iso && (iso < MIN_DATE || iso > MAX_DATE) ? DATE_RANGE_MESSAGE : null;
}
