use ego_tree::NodeRef;
use pyo3::prelude::*;
use scraper::Html;
use scraper::node::{Element, Node};

/// Parse a srcset attribute value per the HTML specification's model:
/// candidates are separated by commas, but a URL may itself contain commas as
/// long as it does not start or end with one, so split on whitespace and only
/// treat trailing commas as separators.
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

/// Extract the URL from a `Refresh` header or `<meta http-equiv="refresh">` value.
#[pyfunction]
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

/// Extract the base href and link URLs from an HTML document, in document
/// order. Link order carries no meaning for the crawler.
#[pyfunction]
fn extract_links(html: &str) -> (String, Vec<String>) {
    let doc = Html::parse_document(html);

    let mut base_href = String::new();
    let mut base_found = false;
    let mut links: Vec<String> = Vec::new();

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
            "a" | "area" | "link" => push_attr(&mut links, el, "href"),
            "iframe" | "script" | "audio" | "track" | "embed" => push_attr(&mut links, el, "src"),
            "img" | "source" => {
                push_attr(&mut links, el, "src");
                push_srcset(&mut links, el);
            }
            "video" => {
                push_attr(&mut links, el, "src");
                push_attr(&mut links, el, "poster");
            }
            "object" => push_attr(&mut links, el, "data"),
            "input" => {
                push_attr(&mut links, el, "src");
                push_formaction(&mut links, el, node);
            }
            "button" => push_formaction(&mut links, el, node),
            "form" => {
                if form_method(el) == "get" {
                    push_attr(&mut links, el, "action");
                }
            }
            "meta" => {
                if el
                    .attr("http-equiv")
                    .is_some_and(|value| value.eq_ignore_ascii_case("refresh"))
                    && let Some(url) = parse_refresh(el.attr("content").unwrap_or(""))
                {
                    links.push(url.trim().to_string());
                }
            }
            _ => {}
        }
    }

    (base_href, links)
}

#[pymodule(name = "_extract")]
fn django_crawl_extract(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(extract_links, m)?)?;
    m.add_function(wrap_pyfunction!(parse_refresh, m)?)?;
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
        assert_eq!(parse_srcset("/a.png,/b.png 2x"), vec!["/a.png,/b.png"]);
        assert_eq!(
            parse_srcset("/crop=10,20,300,200/img.jpg 1x"),
            vec!["/crop=10,20,300,200/img.jpg"]
        );
        assert_eq!(
            parse_srcset("/a.png,, ,/b.png 2x"),
            vec!["/a.png", "/b.png"]
        );
        assert_eq!(
            parse_srcset("/a.png 1x,/b.png 2x"),
            vec!["/a.png", "/b.png"]
        );
        assert_eq!(
            parse_srcset("data:image/png;base64,iVBORw0KGgo 1x"),
            vec!["data:image/png;base64,iVBORw0KGgo"]
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
    fn extract_links_in_document_order() {
        let (base, links) = extract_links(
            "<base href=\"/sub/\"><img src=\"/i.png\"><a href=\"x\">x</a>\
             <form action=\"/f/\"><button formaction=\"/fa/\">b</button></form>",
        );
        assert_eq!(base, "/sub/");
        assert_eq!(links, vec!["/i.png", "x", "/f/", "/fa/"]);
    }
}
