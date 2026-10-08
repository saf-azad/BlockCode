/** Python or R couldn't be started in the browser (offline, a blocked download, an old browser). */
export class RuntimeLoadError extends Error {
  constructor(public lang: string, detail: string) {
    super(`${lang} couldn't start in your browser: ${detail}`);
  }
}

/** Progress shown while a run waits on downloads ("Installing ggplot2…"); null when it's running. */
export type Status = (text: string | null) => void;
