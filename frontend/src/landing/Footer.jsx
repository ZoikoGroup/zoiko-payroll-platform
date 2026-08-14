import { Link } from "react-router-dom";

const styles = {
  root: {
    backgroundColor: "#082B45",
    color: "#ffffff",
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
    width: "100%",
    marginTop: "48px",
  },
  main: {
    maxWidth: "1100px",
    margin: "0 auto",
    padding: "40px 28px",
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
    gap: "28px",
  },
  brand: {},
  logoWrap: {
    display: "flex",
    alignItems: "center",
    gap: "10px",
    marginBottom: "14px",
  },
  logoIcon: {
    width: "36px",
    height: "36px",
    borderRadius: "8px",
    objectFit: "contain",
  },
  logoText: { fontSize: "16px", fontWeight: "700", color: "#ffffff" },
  brandDesc: {
    fontSize: "12.5px",
    color: "rgba(255,255,255,0.55)",
    lineHeight: "1.5",
    marginBottom: "18px",
  },
  colTitle: {
    fontSize: "11.5px",
    fontWeight: "700",
    color: "#20A9E8",
    textTransform: "uppercase",
    letterSpacing: "0.08em",
    marginBottom: "14px",
  },
  list: { listStyle: "none", padding: "0", margin: "0" },
  item: { marginBottom: "10px" },
  link: {
    color: "rgba(255,255,255,0.72)",
    textDecoration: "none",
    fontSize: "13px",
    lineHeight: "1.4",
    display: "block",
  },
  legal: {
    borderTop: "1px solid rgba(255,255,255,0.1)",
    maxWidth: "1100px",
    margin: "0 auto",
    padding: "20px 28px 28px",
    fontSize: "12px",
    color: "rgba(255,255,255,0.4)",
    display: "flex",
    flexWrap: "wrap",
    gap: "6px 20px",
    justifyContent: "center",
  },
};

export default function Footer() {
  return (
    <footer style={styles.root}>
      <div style={styles.main}>
        <div style={styles.brand}>
          <div style={styles.logoWrap}>
            <img src="/zoikopayroll-icon.png" alt="" style={styles.logoIcon} />
            <span style={styles.logoText}>Zoiko Payroll</span>
          </div>
          <p style={styles.brandDesc}>
            Payroll, tax and statutory compliance on the connected Zoiko One platform.
          </p>
        </div>

        <div>
          <div style={styles.colTitle}>Product</div>
          <ul style={styles.list}>
            <li style={styles.item}>
              <Link to="/register" style={styles.link}>Create your account</Link>
            </li>
            <li style={styles.item}>
              <Link to="/login" style={styles.link}>Sign in</Link>
            </li>
            <li style={styles.item}>
              <a href="https://zoikoone.com" target="_blank" rel="noopener noreferrer" style={styles.link}>
                Explore Zoiko One
              </a>
            </li>
          </ul>
        </div>

        <div>
          <div style={styles.colTitle}>Support</div>
          <ul style={styles.list}>
            <li style={styles.item}>
              <Link to="/forgot-password" style={styles.link}>Forgot password</Link>
            </li>
            <li style={styles.item}>
              <a href="https://zoikoone.com" target="_blank" rel="noopener noreferrer" style={styles.link}>
                Help center
              </a>
            </li>
            <li style={styles.item}>
              <a href="https://zoikoone.com" target="_blank" rel="noopener noreferrer" style={styles.link}>
                Contact support
              </a>
            </li>
          </ul>
        </div>
      </div>

      <div style={styles.legal}>
        <span>© 2026 Zoiko Group. All rights reserved. · ZoikoOne™</span>
        <span>Payroll platform — a Zoiko One product.</span>
      </div>
    </footer>
  );
}
