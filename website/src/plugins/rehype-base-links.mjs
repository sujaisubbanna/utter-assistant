/**
 * Prefix root-relative links in Markdown/MDX content with the site's `base` and,
 * on translated pages, with the page's locale.
 *
 * Astro and Starlight prefix the sidebar, hero actions and asset URLs, but links
 * written inside page content (`[text](/guides/x/)`) are emitted as written.
 * On a subpath deployment (`base` not `/`) that would 404, and on a translated
 * page (`/de/guides/x/`) a bare `/guides/x/` link would jump back to the English
 * page. This plugin rewrites `href="/..."` on `<a>` elements and on MDX
 * components such as `<LinkCard href="/..."/>`.
 *
 * It skips protocol-relative URLs (`//host`) and links already carrying the base
 * or the locale prefix, so it is idempotent. Fallback pages (English content
 * served under a locale prefix) keep English links, which is intentional: the
 * content itself is still English.
 *
 * @param {{ base?: string, locales?: string[] }} options
 */
export default function rehypeBaseLinks({ base = '/', locales = [] } = {}) {
  const prefix = base === '/' ? '' : base.replace(/\/+$/, '');
  const docsDir = /[/\\]content[/\\]docs[/\\]([^/\\]+)[/\\]/;

  /** Locale directory a source file lives under, if any (e.g. `de`). */
  const localeOf = (file) => {
    const path = typeof file?.path === 'string' ? file.path : '';
    const match = path.match(docsDir);
    return match && locales.includes(match[1]) ? match[1] : '';
  };

  const rewrite = (href, locale) => {
    if (typeof href !== 'string') return href;
    if (!href.startsWith('/') || href.startsWith('//')) return href;

    // Split off any trailing anchor so the locale is inserted before `#`.
    const hashIndex = href.indexOf('#');
    const hash = hashIndex === -1 ? '' : href.slice(hashIndex);
    let path = hashIndex === -1 ? href : href.slice(0, hashIndex);

    // Idempotency: drop an already-present base before adding it back.
    if (prefix && (path === prefix || path.startsWith(prefix + '/'))) {
      path = path.slice(prefix.length) || '/';
    }

    if (locale) {
      const alreadyLocalized =
        path === `/${locale}` || path === `/${locale}/` || path.startsWith(`/${locale}/`);
      if (!alreadyLocalized) {
        path = path === '/' ? `/${locale}/` : `/${locale}${path}`;
      }
    }

    return prefix + path + hash;
  };

  const walk = (node, locale) => {
    if (!node || typeof node !== 'object') return;
    if (node.type === 'element' && node.tagName === 'a' && node.properties) {
      node.properties.href = rewrite(node.properties.href, locale);
    }
    if (
      (node.type === 'mdxJsxFlowElement' || node.type === 'mdxJsxTextElement') &&
      Array.isArray(node.attributes)
    ) {
      for (const attr of node.attributes) {
        if (attr.type === 'mdxJsxAttribute' && attr.name === 'href') {
          attr.value = rewrite(attr.value, locale);
        }
      }
    }
    if (Array.isArray(node.children)) node.children.forEach((child) => walk(child, locale));
  };

  return (tree, file) => walk(tree, localeOf(file));
}
