import { useEffect, useRef, useState } from "react";

// Decorative hero artwork for the sign-in / create-account panels.
//
// The first paint is a ~200-byte blurred copy of the SAME artwork (inlined as
// a data URI), so the panel never shows anything but the current design while
// the full image downloads; the full image is fetched at high priority and
// fades in once decoded (immediately when the browser already has it).
// Imported assets are content-hashed by the build, so they can be cached
// long-term and a new design can never be served from an old cache entry.
export default function HeroArtwork({ src, srcSet, sizes, placeholder, className = "" }) {
  const img = useRef(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (img.current?.complete && img.current.naturalWidth > 0) setLoaded(true);
  }, []);

  return (
    <>
      <div
        aria-hidden="true"
        className={`pointer-events-none absolute inset-0 scale-110 bg-cover blur-xl ${className}`}
        style={{ backgroundImage: `url("${placeholder}")` }}
      />
      <img
        ref={img}
        src={src}
        srcSet={srcSet}
        sizes={sizes}
        alt=""
        aria-hidden="true"
        loading="eager"
        fetchPriority="high"
        onLoad={() => setLoaded(true)}
        className={`pointer-events-none absolute inset-0 h-full w-full object-cover transition-opacity duration-300 ${className} ${loaded ? "opacity-100" : "opacity-0"}`}
      />
    </>
  );
}
