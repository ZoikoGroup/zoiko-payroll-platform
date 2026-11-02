// Brand panel for the create-account page: the designer's panel exported as
// one image (public/auth/register-hero.webp, cropped from the approved
// create-account design). Its words are part of the picture, so the same
// content is repeated as visually hidden text for screen readers. The panel
// keeps the artwork's own proportions and hides below the lg breakpoint.
const REGISTER_HERO_ARTWORK = "/auth/register-hero.webp";

export default function SignupHero() {
  return (
    <aside className="relative hidden aspect-[695/930] w-[47%] shrink-0 self-start overflow-hidden rounded-2xl bg-[#06215f] lg:block">
      <img
        src={REGISTER_HERO_ARTWORK} alt="" aria-hidden="true" decoding="async"
        className="absolute inset-0 h-full w-full object-cover"
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
