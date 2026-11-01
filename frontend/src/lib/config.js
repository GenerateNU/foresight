// Every setting that changes between machines, read once from env vars (see .env.example).
// Vite only exposes variables that start with VITE_.

/** Where the backend lives. */
export const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'
/** The hotel to show until sign-in picks it. */
export const HOTEL_ID = Number(import.meta.env.VITE_HOTEL_ID ?? 1)
/** Serve fake responses from src/api/mocks instead of calling the backend. */
export const USE_MOCKS = import.meta.env.VITE_USE_MOCKS === 'true'
