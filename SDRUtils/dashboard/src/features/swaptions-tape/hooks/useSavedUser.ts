// Hook for persisting current user in localStorage
// TODO: Extract full implementation from SwaptionTradeTape.tsx (lines 3815, 3917-3934)

import { useEffect, useState } from 'react';

const STORAGE_KEY = 'swaptionManualUser';

export interface UseSavedUserReturn {
  currentUser: string;
  setCurrentUser: (user: string) => void;
}

/**
 * Manages current user state with localStorage persistence
 *
 * @returns Current user and setter function
 */
export function useSavedUser(): UseSavedUserReturn {
  const [currentUser, setCurrentUser] = useState('');

  // Load from localStorage on mount
  useEffect(() => {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved) {
      setCurrentUser(saved);
    }
  }, []);

  // Save to localStorage on change
  useEffect(() => {
    if (currentUser) {
      localStorage.setItem(STORAGE_KEY, currentUser);
    }
  }, [currentUser]);

  return {
    currentUser,
    setCurrentUser,
  };
}
