/**
 * Prefix root-relative links in Markdown/MDX content with the site's `base`.
 *
 * Astro and Starlight prefix the sidebar, hero actions and asset URLs, but
 * links written inside page content (`[text](/guides/x/)`) are emitted as
 * written. Because this site is served from a subpath on GitHub Pages
 * (`/utter-assistant/`), that would 404. This plugin rewrites `href="/..."`
 * on `<a>` elements and on MDX components such as `<LinkCard href="/..."/>`.
 * It skips protocol-relative URLs (`//host`) and links already carrying the
 * base, so it is idempotent.
 */
export default function rehypeBaseLinks({ base }) {
  const prefix = base.endsWith('/') ? base.slice(0, -1) : base;
  const rewrite = (href) => {
    if (typeof href !== 'string') return href;
    if (!href.startsWith('/') || href.startsWith('//')) return href;
    if (href === prefix || href.startsWith(prefix + '/')) return href;
    return prefix + href;
  };
  const walk = (node) => {
    if (!node || typeof node !== 'object') return;
    if (node.type === 'element' && node.tagName === 'a' && node.properties) {
      node.properties.href = rewrite(node.properties.href);
    }
    if (
      (node.type === 'mdxJsxFlowElement' || node.type === 'mdxJsxTextElement') &&
      Array.isArray(node.attributes)
    ) {
      for (const attr of node.attributes) {
        if (attr.type === 'mdxJsxAttribute' && attr.name === 'href') {
          attr.value = rewrite(attr.value);
        }
      }
    }
    if (Array.isArray(node.children)) node.children.forEach(walk);
  };
  return (tree) => walk(tree);
}
