use ego_tree::NodeRef;
use pyo3::prelude::*;
use scraper::Html;
use scraper::node::{Element, Node};

/// Parse a srcset attribute value per the HTML specification's model:
/// candidates are separated by commas, but a URL may itself contain commas as
/// long as it does not start or end with one, so split on whitespace and only
/// treat trailing commas as separators.
#[pyfunction]
fn parse_srcset(value: &str) -> Vec<String> {
    let mut urls = Vec::new();
    let bytes = value.as_bytes();
    let mut pos = 0;
    let length = bytes.len();
    while pos < length {
        while pos < length && (bytes[pos].is_ascii_whitespace() || bytes[pos] == b',') {
            pos += 1;
        }
        let start = pos;
        while pos < length && !bytes[pos].is_ascii_whitespace() {
            pos += 1;
        }
        let mut url = &value[start..pos];
        if url.ends_with(',') {
            url = url.trim_end_matches(',');
        } else {
            // Skip the descriptor, up to the next comma.
            while pos < length && bytes[pos] != b',' {
                pos += 1;
            }
        }
        if !url.is_empty() {
            urls.push(url.to_string());
        }
    }
    urls
}

/// Extract the URL from a `<meta http-equiv="refresh">` content value,
/// matching django_crawl.ext.html.parse_refresh.
fn parse_refresh(content: &str) -> Option<&str> {
    let idx = content.find([';', ','])?;
    let mut rest = content[idx + 1..].trim_start();
    if rest.len() >= 4 && rest[..3].eq_ignore_ascii_case("url") {
        let after = rest[3..].trim_start();
        if let Some(stripped) = after.strip_prefix('=') {
            rest = stripped.trim_start();
        }
    }
    let url = if let Some(quoted) = rest.strip_prefix('"') {
        &quoted[..quoted.find('"').unwrap_or(quoted.len())]
    } else if let Some(quoted) = rest.strip_prefix('\'') {
        &quoted[..quoted.find('\'').unwrap_or(quoted.len())]
    } else {
        rest.split_ascii_whitespace().next().unwrap_or("")
    };
    if url.is_empty() { None } else { Some(url) }
}

fn push_attr(bucket: &mut Vec<String>, el: &Element, attr: &str) {
    if let Some(value) = el.attr(attr)
        && !value.is_empty()
    {
        bucket.push(value.trim().to_string());
    }
}

fn push_srcset(bucket: &mut Vec<String>, el: &Element) {
    if let Some(value) = el.attr("srcset") {
        bucket.extend(parse_srcset(value));
    }
}

/// Push a button/input formaction, if the element is within a form and the
/// effective method, after any formmethod override, is GET.
fn push_formaction(bucket: &mut Vec<String>, el: &Element, node: NodeRef<'_, Node>) {
    let Some(formaction) = el.attr("formaction") else {
        return;
    };
    let Some(form) = node.ancestors().find_map(|ancestor| {
        ancestor
            .value()
            .as_element()
            .filter(|el| el.name() == "form")
            .cloned()
    }) else {
        return;
    };
    let formmethod = el.attr("formmethod").unwrap_or("").trim().to_lowercase();
    let method = if formmethod.is_empty() {
        form_method(&form)
    } else {
        formmethod
    };
    if method == "get" && !formaction.is_empty() {
        bucket.push(formaction.trim().to_string());
    }
}

fn form_method(el: &Element) -> String {
    let method = el.attr("method").unwrap_or("").trim().to_lowercase();
    if method.is_empty() {
        "get".to_string()
    } else {
        method
    }
}

/// Extract the base href and link URLs from an HTML document, in the same
/// order as the former per-selector extraction: grouped by link kind, in
/// document order within each group.
#[pyfunction]
fn extract_links(html: &str) -> (String, Vec<String>) {
    let doc = Html::parse_document(html);

    let mut base_href = String::new();
    let mut base_found = false;
    let mut buckets: [Vec<String>; 17] = std::array::from_fn(|_| Vec::new());

    for node in doc.tree.nodes() {
        let Some(el) = node.value().as_element() else {
            continue;
        };
        match el.name() {
            "base" => {
                if !base_found && let Some(href) = el.attr("href") {
                    base_href = href.trim().to_string();
                    base_found = true;
                }
            }
            "a" => push_attr(&mut buckets[0], el, "href"),
            "area" => push_attr(&mut buckets[1], el, "href"),
            "link" => push_attr(&mut buckets[2], el, "href"),
            "iframe" => push_attr(&mut buckets[3], el, "src"),
            "script" => push_attr(&mut buckets[4], el, "src"),
            "img" => {
                push_attr(&mut buckets[5], el, "src");
                push_srcset(&mut buckets[14], el);
            }
            "source" => {
                push_attr(&mut buckets[6], el, "src");
                push_srcset(&mut buckets[14], el);
            }
            "video" => {
                push_attr(&mut buckets[7], el, "src");
                push_attr(&mut buckets[8], el, "poster");
            }
            "audio" => push_attr(&mut buckets[9], el, "src"),
            "track" => push_attr(&mut buckets[10], el, "src"),
            "object" => push_attr(&mut buckets[11], el, "data"),
            "embed" => push_attr(&mut buckets[12], el, "src"),
            "input" => {
                push_attr(&mut buckets[13], el, "src");
                push_formaction(&mut buckets[15], el, node);
            }
            "button" => push_formaction(&mut buckets[15], el, node),
            "form" => {
                if form_method(el) == "get" {
                    push_attr(&mut buckets[15], el, "action");
                }
            }
            "meta" => {
                if el
                    .attr("http-equiv")
                    .is_some_and(|value| value.eq_ignore_ascii_case("refresh"))
                    && let Some(url) = parse_refresh(el.attr("content").unwrap_or(""))
                {
                    buckets[16].push(url.trim().to_string());
                }
            }
            _ => {}
        }
    }

    (base_href, buckets.into_iter().flatten().collect())
}

#[pymodule(name = "_extract")]
fn django_crawl_extract(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(extract_links, m)?)?;
    m.add_function(wrap_pyfunction!(parse_srcset, m)?)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_srcset_splits_candidates() {
        assert_eq!(parse_srcset(""), Vec::<String>::new());
        assert_eq!(parse_srcset("/a.png"), vec!["/a.png"]);
        assert_eq!(
            parse_srcset("/a.png 1x, /b.png 2x"),
            vec!["/a.png", "/b.png"]
        );
        assert_eq!(parse_srcset("/a.png 100w,"), vec!["/a.png"]);
        assert_eq!(parse_srcset(" , "), Vec::<String>::new());
        assert_eq!(
            parse_srcset("/crop=10,20,300,200/img.jpg 1x"),
            vec!["/crop=10,20,300,200/img.jpg"]
        );
    }

    #[test]
    fn parse_refresh_extracts_urls() {
        assert_eq!(parse_refresh("5"), None);
        assert_eq!(parse_refresh("0; url=/x"), Some("/x"));
        assert_eq!(parse_refresh("0;URL='/x'"), Some("/x"));
        assert_eq!(parse_refresh("0; url=\"/x\""), Some("/x"));
        assert_eq!(parse_refresh("0; /x"), Some("/x"));
        assert_eq!(parse_refresh("0;"), None);
    }

    #[test]
    fn extract_links_groups_by_kind() {
        let (base, links) = extract_links(
            "<base href=\"/sub/\"><img src=\"/i.png\"><a href=\"x\">x</a>\
             <form action=\"/f/\"><button formaction=\"/fa/\">b</button></form>",
        );
        assert_eq!(base, "/sub/");
        assert_eq!(links, vec!["x", "/i.png", "/f/", "/fa/"]);
    }
}
