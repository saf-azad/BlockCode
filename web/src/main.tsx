import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import { Gallery } from './explainers/Gallery';
import './styles.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {new URLSearchParams(window.location.search).has('gallery') ? <Gallery /> : <App />}
  </StrictMode>,
);
