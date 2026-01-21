// Loading spinner component
import { HTMLAttributes } from 'react';
import { cn } from '@/lib/utils';

export interface SpinnerProps extends HTMLAttributes<HTMLDivElement> {
  size?: 'sm' | 'md' | 'lg';
  variant?: 'primary' | 'white';
}

/**
 * Animated loading spinner
 */
export function Spinner({ size = 'md', variant = 'primary', className, ...props }: SpinnerProps) {
  const sizeStyles = {
    sm: 'h-4 w-4',
    md: 'h-8 w-8',
    lg: 'h-12 w-12',
  };

  const variantStyles = {
    primary: 'text-blue-600',
    white: 'text-white',
  };

  return (
    <div className={cn('inline-block', className)} {...props}>
      <svg
        className={cn('animate-spin', sizeStyles[size], variantStyles[variant])}
        xmlns="http://www.w3.org/2000/svg"
        fill="none"
        viewBox="0 0 24 24"
      >
        <circle
          className="opacity-25"
          cx="12"
          cy="12"
          r="10"
          stroke="currentColor"
          strokeWidth="4"
        />
        <path
          className="opacity-75"
          fill="currentColor"
          d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
        />
      </svg>
    </div>
  );
}

/**
 * Full-screen loading overlay
 */
export function SpinnerOverlay({ message }: { message?: string }) {
  return (
    <div className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-black bg-opacity-50">
      <Spinner size="lg" variant="white" />
      {message && <p className="mt-4 text-white text-lg">{message}</p>}
    </div>
  );
}
