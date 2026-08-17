// Lightweight i18n layer for the Assist module.
// Keys are flat strings; interpolate placeholders with {var}.

const LOCALE_KEY = "zoiko_payroll_assist_locale";

export const ASSIST_LOCALES = {
  en: {
    name: "English",
    flag: "EN",
  },
  fr: {
    name: "Français",
    flag: "FR",
  },
  es: {
    name: "Español",
    flag: "ES",
  },
  hi: {
    name: "हिन्दी",
    flag: "HI",
  },
};

const MESSAGES = {
  en: {
    "assist.title": "Assist",
    "assist.notice.title": "Assist policy notice",
    "assist.notice.acknowledge": "Acknowledge and continue",
    "assist.newSession": "New session",
    "assist.more": "More",
    "assist.close": "Close",
    "assist.open": "Open Zoiko Payroll Assist",
    "assist.thinking": "Thinking…",
    "assist.placeholder": "Ask about payroll readiness, exceptions, policies…",
    "assist.footer": "Governed by Zoiko Payroll Assist policy · previews & confirmations required for actions",
    "assist.intro": "Hi, I'm {name}. I can summarize payroll run readiness, list exceptions, explain policies and prepare work — but I can never approve payroll, release payments or change protected data.",
    "assist.sources": "Sources ({count})",
    "assist.helpful": "Helpful",
    "assist.notHelpful": "Not helpful",
    "assist.refused": "Governed response · {state}",
    "assist.bootError": "Could not start Assist.",
    "assist.ackError": "Could not acknowledge the notice.",
    "assist.genError": "I could not generate a response.",
    "assist.sendError": "Something went wrong.",
    "assist.tabs.chat": "Chat",
    "assist.tabs.drafts": "Drafts",
    "assist.tabs.history": "History",
    "assist.action.title": "Proposed action · preview",
    "assist.action.confirm": "Confirm",
    "assist.action.cancel": "Cancel",
    "assist.action.confirming": "Confirming…",
    "assist.action.riskTier": "Risk tier {tier}",
    "assist.action.before": "Before",
    "assist.action.after": "After",
    "assist.action.confirmed": "Action confirmed",
    "assist.action.cancelled": "Action cancelled",
    "assist.action.receipt": "Receipt {id}",
    "assist.action.target": "Target: {type}",
    "assist.handoff.title": "Escalate to support",
    "assist.handoff.confirm": "Create handoff case",
    "assist.handoff.summary": "Summary",
    "assist.handoff.summaryPlaceholder": "Describe what you need help with…",
    "assist.handoff.reason": "Reason",
    "assist.handoff.destination": "Send to",
    "assist.handoff.preview": "Preview handoff",
    "assist.handoff.created": "Handoff created",
    "assist.handoff.caseRef": "Case {id}",
    "assist.handoff.requiresCase": "This case should go to the support team.",
    "assist.stop": "Stop generating",
    "assist.stopped": "Stopped.",
    "assist.drafts.ready": "Draft ready — see the Drafts tab",
    "assist.drafts.empty": "No drafts yet. Save a response as a draft to reuse it later.",
    "assist.drafts.new": "New draft",
    "assist.drafts.save": "Save draft",
    "assist.drafts.saved": "Draft saved",
    "assist.drafts.delete": "Delete",
    "assist.drafts.edit": "Edit",
    "assist.drafts.type": "Type",
    "assist.drafts.content": "Content",
    "assist.drafts.title": "Drafts",
    "assist.drafts.deleteConfirm": "Delete this draft?",
    "assist.history.empty": "No past sessions.",
    "assist.history.title": "Session history",
    "assist.history.resume": "Resume",
    "assist.history.archive": "Archive",
    "assist.history.archived": "Archived",
    "assist.history.active": "Active",
    "assist.history.createdAt": "Created {date}",
    "assist.history.sessions": "Sessions",
    "assist.sse.live": "Generating…",
    "assist.locale": "Language",
  },
  fr: {
    "assist.title": "Assist",
    "assist.notice.title": "Avis de politique Assist",
    "assist.notice.acknowledge": "Accepter et continuer",
    "assist.newSession": "Nouvelle session",
    "assist.more": "Plus",
    "assist.close": "Fermer",
    "assist.open": "Ouvrir Zoiko Payroll Assist",
    "assist.thinking": "Réflexion…",
    "assist.placeholder": "Posez une question sur la paie, les exceptions, les politiques…",
    "assist.footer": "Régi par la politique Zoiko Payroll Assist · aperçus et confirmations requis pour les actions",
    "assist.intro": "Bonjour, je suis {name}. Je peux résumer la préparation des paies, lister les exceptions, expliquer les politiques et préparer le travail — mais je ne peux jamais approuver une paie, libérer des paiements ni modifier des données protégées.",
    "assist.sources": "Sources ({count})",
    "assist.helpful": "Utile",
    "assist.notHelpful": "Pas utile",
    "assist.refused": "Réponse encadrée · {state}",
    "assist.bootError": "Impossible de démarrer Assist.",
    "assist.ackError": "Impossible d'accepter l'avis.",
    "assist.genError": "Je n'ai pas pu générer de réponse.",
    "assist.sendError": "Une erreur s'est produite.",
    "assist.tabs.chat": "Chat",
    "assist.tabs.drafts": "Brouillons",
    "assist.tabs.history": "Historique",
    "assist.action.title": "Action proposée · aperçu",
    "assist.action.confirm": "Confirmer",
    "assist.action.cancel": "Annuler",
    "assist.action.confirming": "Confirmation…",
    "assist.action.riskTier": "Niveau de risque {tier}",
    "assist.action.before": "Avant",
    "assist.action.after": "Après",
    "assist.action.confirmed": "Action confirmée",
    "assist.action.cancelled": "Action annulée",
    "assist.action.receipt": "Reçu {id}",
    "assist.action.target": "Cible : {type}",
    "assist.handoff.title": "Transférer au support",
    "assist.handoff.confirm": "Créer un dossier de transfert",
    "assist.handoff.summary": "Résumé",
    "assist.handoff.summaryPlaceholder": "Décrivez ce dont vous avez besoin…",
    "assist.handoff.reason": "Motif",
    "assist.handoff.destination": "Destinataire",
    "assist.handoff.preview": "Aperçu du transfert",
    "assist.handoff.created": "Dossier créé",
    "assist.handoff.caseRef": "Dossier {id}",
    "assist.handoff.requiresCase": "Ce dossier doit être transmis à l'équipe support.",
    "assist.stop": "Arrêter la génération",
    "assist.stopped": "Arrêté.",
    "assist.drafts.ready": "Brouillon prêt — voir l'onglet Brouillons",
    "assist.drafts.empty": "Aucun brouillon. Enregistrez une réponse en brouillon pour la réutiliser.",
    "assist.drafts.new": "Nouveau brouillon",
    "assist.drafts.save": "Enregistrer le brouillon",
    "assist.drafts.saved": "Brouillon enregistré",
    "assist.drafts.delete": "Supprimer",
    "assist.drafts.edit": "Modifier",
    "assist.drafts.type": "Type",
    "assist.drafts.content": "Contenu",
    "assist.drafts.title": "Brouillons",
    "assist.drafts.deleteConfirm": "Supprimer ce brouillon ?",
    "assist.history.empty": "Aucune session passée.",
    "assist.history.title": "Historique des sessions",
    "assist.history.resume": "Reprendre",
    "assist.history.archive": "Archiver",
    "assist.history.archived": "Archivé",
    "assist.history.active": "Active",
    "assist.history.createdAt": "Créée le {date}",
    "assist.history.sessions": "Sessions",
    "assist.sse.live": "Génération…",
    "assist.locale": "Langue",
  },
};

export function getAssistLocale() {
  const stored = localStorage.getItem(LOCALE_KEY);
  return stored && ASSIST_LOCALES[stored] ? stored : "en";
}

export function setAssistLocale(locale) {
  localStorage.setItem(LOCALE_KEY, locale);
}

export function t(key, vars = {}) {
  const locale = getAssistLocale();
  let template = MESSAGES[locale]?.[key];
  if (template === undefined) template = MESSAGES.en[key] ?? key;
  return template.replace(/\{(\w+)\}/g, (_, name) => (vars[name] !== undefined ? String(vars[name]) : `{${name}}`));
}

export function useAssistLocaleState() {
  return getAssistLocale();
}

export function formatAssistDate(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  const locale = getAssistLocale();
  try {
    return new Intl.DateTimeFormat(locale === "en" ? "en-GB" : locale, {
      day: "numeric",
      month: "short",
      year: "numeric",
    }).format(date);
  } catch {
    return date.toLocaleDateString();
  }
}
