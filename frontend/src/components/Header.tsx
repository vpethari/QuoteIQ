import { AtkoreLogo } from "./Icons";
import { useState, type MouseEvent } from "react";

interface Props {
  onGetStarted: () => void;
}

export function Header({ onGetStarted }: Props) {
  const [open, setOpen] = useState(false);
  const [logoFailed, setLogoFailed] = useState(false);

  function placeholder(event: MouseEvent<HTMLAnchorElement>) {
    event.preventDefault();
  }

  return (
    <header className="site-header">
      <a className="skip-link" href="#upload">
        Skip to upload
      </a>
      <div className="site-header-inner">
        <a className="logo" href="#top" aria-label="Atkore QuoteIQ">
          {logoFailed ? (
            <AtkoreLogo />
          ) : (
            <img
              className="atkore-logo-img"
              src="/atkore-logo.png"
              alt="Atkore"
              height={32}
              onError={() => setLogoFailed(true)}
            />
          )}
        </a>
        <button
          type="button"
          className="nav-toggle"
          aria-expanded={open}
          aria-controls="site-nav"
          onClick={() => setOpen((value) => !value)}
        >
          {open ? "Close menu" : "Menu"}
        </button>
        <nav id="site-nav" className={open ? "site-nav is-open" : "site-nav"} aria-label="Primary">
          <div className="nav-links">
            <a href="#product" onClick={placeholder}>
              Product
            </a>
            <a href="#resources" onClick={placeholder}>
              Resources
            </a>
          </div>
          <div className="nav-auth">
            <a href="#login" className="nav-login" onClick={placeholder}>
              Log in
            </a>
            <button type="button" className="btn-navy" onClick={onGetStarted}>
              Get Started
            </button>
          </div>
        </nav>
      </div>
    </header>
  );
}
