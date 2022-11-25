from django.http import HttpResponseNotAllowed


def method_router(csrf_exempt: bool | None = None, **views):
    """
    Returns a view that dispatches to different views based on the request method.
    This allows us to have plain function views for each HTTP method, rather than
    having to use ifs within the view or use class based views to separate logic
    for different HTTP methods.

    Usage example in a urls.py file:
    ```
        path(
            "some-path",
            method_router(
                PUT=update_view,
                DELETE=delete_view,
            ),
            name="url-name",
        )
    ```
    """

    if csrf_exempt is None:
        csrf_exempt_values = {
            getattr(view, "csrf_exempt", False)
            for method, view in views.items()
            if method not in ["GET", "HEAD", "OPTIONS", "TRACE"]
        }
        if len(csrf_exempt_values) > 1:
            raise RuntimeError(
                "You are using method_router with views that have different csrf_exempt values. "
                "This will cause none of the views to be csrf_exempt.\n"
                "Either use csrf_exempt on all views or none."
            )
        csrf_exempt = all(csrf_exempt_values)

    def invalid_method(self, request, *args, **kwargs):
        return HttpResponseNotAllowed(self.views.keys())

    def call_view(request, *args, **kwargs):
        view = views.get(request.method, invalid_method)
        return view(request, *args, **kwargs)

    call_view.csrf_exempt = csrf_exempt  # type: ignore[attr-defined]

    call_view._method_router_views = views  # type: ignore[attr-defined]

    return call_view
