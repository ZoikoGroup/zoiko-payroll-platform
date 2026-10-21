import { useEffect, useState } from "react";

// Re-renders the caller every `intervalMs` with the current epoch ms - the
// clock behind every Support Access countdown.
export default function useNow(intervalMs = 1000) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}
