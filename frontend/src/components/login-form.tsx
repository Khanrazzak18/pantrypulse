"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useRef, useState } from "react";

import { ApiRequestError, apiFetch, type User } from "@/lib/api/client";
import { roleHome } from "@/lib/roles";
import { CONTROL_MESSAGE, controlCharError } from "@/lib/text";

type Fields = { email: string; password: string };
type Errors = Partial<Record<keyof Fields, string>>;

const EMAIL_PATTERN = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

function validate({ email, password }: Fields): Errors {
  const errors: Errors = {};
  if (!email.trim()) errors.email = "Enter your email address.";
  else if (!EMAIL_PATTERN.test(email.trim())) errors.email = "Enter a valid email address.";
  else if (controlCharError(email)) errors.email = CONTROL_MESSAGE;
  if (!password) errors.password = "Enter your password.";
  else if (controlCharError(password)) errors.password = CONTROL_MESSAGE;
  return errors;
}

export function LoginForm({ next }: { next: string | null }) {
  const router = useRouter();
  const [values, setValues] = useState<Fields>({ email: "", password: "" });
  const [touched, setTouched] = useState<Partial<Record<keyof Fields, boolean>>>({});
  const [serverErrors, setServerErrors] = useState<Errors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const emailRef = useRef<HTMLInputElement>(null);
  const passwordRef = useRef<HTMLInputElement>(null);

  const clientErrors = validate(values);
  const errorFor = (field: keyof Fields) =>
    touched[field] ? (clientErrors[field] ?? serverErrors[field]) : serverErrors[field];

  function update(field: keyof Fields, value: string) {
    setValues((v) => ({ ...v, [field]: value }));
    setServerErrors((e) => ({ ...e, [field]: undefined }));
    setFormError(null);
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting) return;
    setTouched({ email: true, password: true });
    const errors = validate(values);
    if (errors.email) return emailRef.current?.focus();
    if (errors.password) return passwordRef.current?.focus();

    setSubmitting(true);
    setFormError(null);
    try {
      const user = await apiFetch<User>("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ email: values.email.trim(), password: values.password }),
      });
      router.replace(next ?? roleHome(user.role));
      // Stay in the submitting state: the page is about to change.
    } catch (err) {
      setSubmitting(false);
      if (err instanceof ApiRequestError && err.status === 422 && Array.isArray(err.details)) {
        const fromServer: Errors = {};
        for (const d of err.details as { field: string; message: string }[]) {
          if (d.field === "email" || d.field === "password") fromServer[d.field] = d.message;
        }
        setServerErrors(fromServer);
        setFormError(Object.keys(fromServer).length ? null : err.message);
      } else {
        setFormError(err instanceof Error ? err.message : "Something went wrong. Try again.");
      }
      passwordRef.current?.focus();
    }
  }

  const emailError = errorFor("email");
  const passwordError = errorFor("password");
  const inputClass = (invalid: boolean) =>
    `mt-1 block w-full rounded-md border px-3 py-2 text-base shadow-sm outline-none focus:ring-2 ${
      invalid
        ? "border-red-500 focus:ring-red-200"
        : "border-stone-300 focus:border-green-700 focus:ring-green-200"
    }`;

  return (
    <form onSubmit={onSubmit} noValidate aria-busy={submitting} className="space-y-4">
      <p role="status" className="sr-only">
        {submitting ? "Signing in…" : ""}
      </p>
      {formError && (
        <div role="alert" className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-800">
          {formError}
        </div>
      )}

      <div>
        <label htmlFor="email" className="block text-sm font-medium">
          Email
        </label>
        <input
          ref={emailRef}
          id="email"
          name="email"
          type="email"
          autoComplete="email"
          maxLength={254}
          inputMode="email"
          value={values.email}
          readOnly={submitting}
          onChange={(e) => update("email", e.target.value)}
          onBlur={() => setTouched((t) => ({ ...t, email: true }))}
          aria-invalid={Boolean(emailError)}
          aria-describedby={emailError ? "email-error" : undefined}
          className={inputClass(Boolean(emailError))}
        />
        {emailError && (
          <p id="email-error" className="mt-1 text-sm text-red-700">
            {emailError}
          </p>
        )}
      </div>

      <div>
        <label htmlFor="password" className="block text-sm font-medium">
          Password
        </label>
        <input
          ref={passwordRef}
          id="password"
          name="password"
          type="password"
          autoComplete="current-password"
          maxLength={200}
          value={values.password}
          readOnly={submitting}
          onChange={(e) => update("password", e.target.value)}
          onBlur={() => setTouched((t) => ({ ...t, password: true }))}
          aria-invalid={Boolean(passwordError)}
          aria-describedby={passwordError ? "password-error" : undefined}
          className={inputClass(Boolean(passwordError))}
        />
        {passwordError && (
          <p id="password-error" className="mt-1 text-sm text-red-700">
            {passwordError}
          </p>
        )}
      </div>

      <button
        type="submit"
        disabled={submitting}
        className="flex w-full items-center justify-center gap-2 rounded-md bg-green-700 px-4 py-2.5 font-medium text-white hover:bg-green-800 focus:outline-none focus:ring-2 focus:ring-green-300 disabled:cursor-not-allowed disabled:opacity-70"
      >
        {submitting && (
          <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="3" opacity="0.3" />
            <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
          </svg>
        )}
        {submitting ? "Signing in…" : "Sign in"}
      </button>
    </form>
  );
}
