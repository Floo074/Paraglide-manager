import { Info, Map as MapIcon, Monitor, Moon, Server, Sun } from "lucide-react";
import { NavLink, Link } from "react-router-dom";
import { useTheme } from "../../hooks/useTheme";
import { Logo } from "./Logo";

export function AppHeader() {
  const { pref, cycle } = useTheme();
  const ThemeIcon = pref === "dark" ? Moon : pref === "light" ? Sun : Monitor;
  const themeLabel = pref === "dark" ? "Thème sombre" : pref === "light" ? "Thème clair" : "Thème du système";
  return (
    <header className="app-header no-print">
      <Link to="/" className="app-header__brand" aria-label="Paraglide Manager — accueil">
        <Logo />
        <span className="app-header__name">
          Paraglide<span className="app-header__name2"> Manager</span>
        </span>
      </Link>
      <nav className="app-header__nav" aria-label="Navigation principale">
        <NavLink to="/" end className="nav-link">
          <MapIcon size={17} aria-hidden />
          <span>Planifier</span>
        </NavLink>
        <NavLink to="/sources" className="nav-link">
          <Server size={17} aria-hidden />
          <span>Sources</span>
        </NavLink>
        <NavLink to="/a-propos" className="nav-link">
          <Info size={17} aria-hidden />
          <span>À propos</span>
        </NavLink>
      </nav>
      <button type="button" className="icon-btn" onClick={cycle} title={`${themeLabel} (changer)`} aria-label={`${themeLabel}, cliquer pour changer`}>
        <ThemeIcon size={18} aria-hidden />
      </button>
    </header>
  );
}
