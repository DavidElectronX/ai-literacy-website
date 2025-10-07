(function () {
    const NAV_PLACEHOLDER_SELECTOR = '[data-nav-placeholder]';
    const NAV_LINK_SELECTOR = '[data-nav-link]';
    const NAV_TOGGLE_SELECTOR = '.site-nav__toggle';

    function normalizePath(pathname) {
        if (!pathname) {
            return 'index.html';
        }
        const path = pathname.split('?')[0].split('#')[0];
        return path === '' ? 'index.html' : path;
    }

    function markActiveLinks(navElement) {
        const currentPath = normalizePath(window.location.pathname.split('/').pop());
        const links = navElement.querySelectorAll(NAV_LINK_SELECTOR);
        let expandedParent = null;

        links.forEach((link) => {
            const href = normalizePath(link.getAttribute('href'));
            if (href === currentPath) {
                link.classList.add('is-active');
                link.setAttribute('aria-current', 'page');

                const subitem = link.closest('.site-nav__subitem');
                const item = link.closest('.site-nav__item');

                if (subitem) {
                    subitem.classList.add('is-active');
                }

                if (item) {
                    item.classList.add('is-active');

                    if (item.classList.contains('site-nav__item--has-children')) {
                        expandedParent = item;
                    } else {
                        const parentWithChildren = link.closest('.site-nav__item--has-children');
                        if (parentWithChildren) {
                            expandedParent = parentWithChildren;
                        }
                    }
                }
            }
        });

        if (expandedParent) {
            expandedParent.classList.add('is-open');
        }
    }

    function syncToggleState(item) {
        const toggle = item.querySelector(NAV_TOGGLE_SELECTOR);
        const sublist = item.querySelector('.site-nav__sublist');
        const isOpen = item.classList.contains('is-open');

        if (toggle) {
            toggle.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
        }

        if (sublist) {
            if (isOpen) {
                sublist.removeAttribute('hidden');
            } else {
                sublist.setAttribute('hidden', '');
            }
        }
    }

    function attachToggleHandlers(navElement) {
        const itemsWithChildren = navElement.querySelectorAll('.site-nav__item--has-children');

        itemsWithChildren.forEach((item) => {
            syncToggleState(item);

            const toggle = item.querySelector(NAV_TOGGLE_SELECTOR);
            if (!toggle) {
                return;
            }

            toggle.addEventListener('click', () => {
                const isOpen = item.classList.toggle('is-open');
                syncToggleState(item);

                if (isOpen) {
                    item.classList.add('is-open');
                }
            });
        });
    }

    async function loadNavigation(navElement) {
        try {
            const response = await fetch('nav.html', { cache: 'no-cache' });
            if (!response.ok) {
                throw new Error('Failed to load navigation.');
            }

            const html = await response.text();
            navElement.innerHTML = html;

            markActiveLinks(navElement);
            attachToggleHandlers(navElement);
        } catch (error) {
            navElement.innerHTML = '<div class="site-nav__error">Navigation could not be loaded.</div>';
            console.error(error);
        }
    }

    function init() {
        const navElements = document.querySelectorAll(NAV_PLACEHOLDER_SELECTOR);
        if (!navElements.length) {
            return;
        }

        navElements.forEach((navElement) => {
            loadNavigation(navElement);
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
