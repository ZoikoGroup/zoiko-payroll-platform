import React from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import StepUpAuthModal from "./components/StepUpAuthModal";
import SessionTimeoutWarning from "./components/SessionTimeoutWarning";
import { AuthProvider } from "./context/AuthContext";
import { OrganizationProvider } from "./context/OrganizationContext";
import { DarkModeProvider } from "./context/DarkModeContext";
import "./index.css";

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <OrganizationProvider>
          <DarkModeProvider>
            <App />
            <StepUpAuthModal />
            <SessionTimeoutWarning />
          </DarkModeProvider>
        </OrganizationProvider>
      </AuthProvider>
    </BrowserRouter>
  </React.StrictMode>
);
