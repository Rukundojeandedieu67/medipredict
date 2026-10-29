import { useState, type FormEvent } from "react";

interface LoginViewProps {
  configurationError: string;
  onLogin: (email: string, password: string) => Promise<void>;
}

export function LoginView({ configurationError, onLogin }: LoginViewProps) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      await onLogin(email, password);
    } catch (loginError) {
      setError(
        loginError instanceof Error ? loginError.message : "Sign-in failed."
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="auth-page">
      <section className="auth-card" aria-labelledby="login-title">
        <div className="auth-brand-mark" aria-hidden="true">M</div>
        <p className="auth-eyebrow">RWANDA HEALTH INTELLIGENCE</p>
        <h1 id="login-title">Sign in to MediPredict</h1>
        <p className="auth-description">
          Use the account provided by your workspace administrator.
        </p>
        {(configurationError || error) && (
          <div className="auth-error" role="alert">
            {configurationError || error}
          </div>
        )}
        <form className="auth-form" onSubmit={(event) => void submit(event)}>
          <label htmlFor="login-email">Email address</label>
          <input
            id="login-email"
            type="email"
            autoComplete="username"
            required
            maxLength={254}
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
          <label htmlFor="login-password">Password</label>
          <input
            id="login-password"
            type="password"
            autoComplete="current-password"
            required
            maxLength={256}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
          <button type="submit" className="auth-submit" disabled={submitting}>
            {submitting ? "Signing in…" : "Sign in"}
          </button>
        </form>
        <p className="auth-footer">Protected access · Accounts are admin-created</p>
      </section>
    </main>
  );
}
