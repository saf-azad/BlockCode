// Every hover animation at once (open /?gallery), like the "Block explainers" board in the design.
import { useState } from 'react';
import { applyTheme } from '../theme';
import { LANGS, LANG_LABEL, type Lang } from '../types';
import { Diagram } from './Explainer';
import { scenes } from './scenes';

const NAMES: Record<string, string> = {
  from: 'From', join: 'Join (matching rows)', join_left: 'Join (keep all rows)', where: 'Where', derive: 'New column',
  group: 'Group by', having: 'Having', select: 'Select', order: 'Order by', limit: 'Limit', plot: 'Plot', foreach: 'For each',
  print: 'Print', repeat: 'Repeat', if: 'If / else', while: 'While', setvar: 'Set var', changevar: 'Change var', raw: 'Code',
};

export function Gallery() {
  const [lang, setLang] = useState<Lang>('sql');
  applyTheme(lang);
  return (
    <div style={{ padding: 40, background: 'var(--c1)', minHeight: '100vh' }}>
      <h1 style={{ fontFamily: 'var(--head)', fontWeight: 900, fontSize: 56, margin: '0 0 8px', textShadow: '4px 4px 0 var(--acc)' }}>Hover explainers</h1>
      <p style={{ maxWidth: 640, color: 'var(--muted)' }}>Each cube is one row. These play beside a block when you hover it.</p>
      <div className="toggle" style={{ display: 'inline-flex', margin: '12px 0 28px' }}>
        {LANGS.map((l) => <button key={l} className={l === lang ? 'on' : ''} onClick={() => setLang(l)}>{LANG_LABEL[l]}</button>)}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 20 }}>
        {Object.keys(scenes(lang)).map((k) => (
          <figure key={k + lang} data-gallery={k} style={{ margin: 0, background: '#fff', border: '2px solid var(--ink)', borderRadius: 14, boxShadow: '5px 5px 0 var(--ink)', padding: 14 }}>
            <Diagram type={k === 'join_left' ? 'join' : k} fields={k === 'join_left' ? { how: 'left' } : {}} lang={lang} width={170} />
            <figcaption style={{ fontFamily: 'var(--head)', fontWeight: 800, fontSize: 16, marginTop: 6 }}>{NAMES[k] ?? k}</figcaption>
          </figure>
        ))}
      </div>
    </div>
  );
}
