// Utility for composing CSS class names.
// Filters out falsy values and joins remaining class strings.

type ClassValue = string | undefined | null | false | 0;

export function cn(...inputs: ClassValue[]): string {
  return inputs.filter(Boolean).join(' ');
}
