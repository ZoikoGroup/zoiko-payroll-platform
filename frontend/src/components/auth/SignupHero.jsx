import registerHero from "../../assets/auth/register-hero.webp";
import registerHero2x from "../../assets/auth/register-hero@2x.webp";
import HeroArtwork from "./HeroArtwork";

// Brand panel for the create-account page: the designer's panel as one image,
// cropped losslessly from the approved create-account design (1x, 695 x 930)
// plus a 2x Lanczos-resampled copy, so high-density screens scale a sharp
// image down instead of stretching the 1x up. Its words are part of the
// picture, so the same content is repeated as visually hidden text for screen
// readers. The panel keeps the artwork's proportions and hides below lg.
// REGISTER_HERO_PLACEHOLDER is an 18 x 24 blurred copy painted first.
const REGISTER_HERO_PLACEHOLDER = "data:image/webp;base64,UklGRv4AAABXRUJQVlA4IPIAAADQBQCdASoSABgAPtFgqE+oJSOiKAgBABoJZACdMoM26V/gMY4XHAZ83g30v8wgJOY+Yv0m5s8AAP7s3qd4ndK90tsgOQqd8AnWol+jCCVyoiu7a5RFFC3MUg1O+RyYDKQu8688SkUDZxZuRjl4hYch1RN0CkRF/bzVhr2D1Wtx0uvdYKC6L3MP3o+pIc/S3jtQROgfh2W47rtQbF04eKhf8l1H/rFlBjBUkz1szuBsq+jJWcSF1e0Jt7Rsbg9Fwn2Po0mP1z0EKHJyRMDtzjXWFYoqPj47qjTJtOZS5CCfTQdjacg8hlkxErK4HbFIursAAA==";

export default function SignupHero() {
  return (
    <aside className="relative hidden aspect-[695/930] w-[47%] shrink-0 self-start overflow-hidden rounded-2xl bg-[#06215f] lg:block">
      <HeroArtwork
        src={registerHero}
        srcSet={`${registerHero} 695w, ${registerHero2x} 1390w`}
        sizes="(min-width: 1440px) 660px, (min-width: 1024px) 46vw, 1px"
        placeholder={REGISTER_HERO_PLACEHOLDER}
      />
      <div className="sr-only">
        <p>Global payroll platform</p>
        <h1>Payroll for a borderless world.</h1>
        <p>Run payroll, stay compliant and take care of your people from one secure platform.</p>
        <ul>
          <li>Global compliance: local payroll, taxes and filings.</li>
          <li>Accurate and automated: pay runs, statutory rates and payslips — done right.</li>
          <li>Secure and reliable: enterprise-grade security and data privacy.</li>
          <li>Built for global teams: from startups to global enterprises.</li>
        </ul>
      </div>
    </aside>
  );
}
