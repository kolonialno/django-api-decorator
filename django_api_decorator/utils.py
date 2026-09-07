from types import UnionType
from typing import Any, Callable, List, Set, Tuple, Union, cast, get_origin

from django.http import HttpRequest, HttpResponse, HttpResponseNotAllowed
from pydantic import BaseModel


def method_router(
    csrf_exempt: bool | None = None,
    **views: Callable[..., HttpResponse],
) -> Callable[..., HttpResponse]:
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

    The returned view is exempt from ``ATOMIC_REQUESTS`` for the database aliases
    that *all* the given views are exempt from, as the router is a single view for
    all the methods. Views decorated with ``@api`` are always exempt, because they
    open the transaction themselves when ``atomic`` is set.
    """

    if csrf_exempt is None:
        csrf_exempt_values = {
            getattr(view, "csrf_exempt", False)
            for method, view in views.items()
            if method not in ["GET", "HEAD", "OPTIONS", "TRACE"]
        }
        if len(csrf_exempt_values) > 1:
            raise RuntimeError(
                "You are using method_router with views that have different csrf_exempt"
                " values. This will cause none of the views to be csrf_exempt.\n"
                "Either use csrf_exempt on all views or none."
            )
        csrf_exempt = all(csrf_exempt_values)

    def invalid_method(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        return HttpResponseNotAllowed(views.keys())

    def call_view(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        view = views.get(cast(str, request.method), invalid_method)
        # The views are Callable[..., HttpResponse], so mypy treats forwarding
        # *args/**kwargs to them as an untyped call returning Any.
        response: HttpResponse = view(  # type: ignore[no-untyped-call]
            request, *args, **kwargs
        )
        return response

    call_view.csrf_exempt = csrf_exempt  # type: ignore[attr-defined]

    # Django looks for _non_atomic_requests on the resolved view to decide if it
    # should skip the ATOMIC_REQUESTS transaction. call_view is a new function, so
    # without this the marker on the wrapped views is lost and their requests are
    # run in a transaction after all.
    non_atomic_requests: list[set[str]] = [
        set(getattr(view, "_non_atomic_requests", set())) for view in views.values()
    ]
    call_view._non_atomic_requests = (  # type: ignore[attr-defined]
        set.intersection(*non_atomic_requests) if non_atomic_requests else set()
    )

    call_view._method_router_views = views  # type: ignore[attr-defined]

    return cast(Callable[..., HttpResponse], call_view)


def is_list_type(annotation: Any) -> bool:
    """
    Check if the given annotation is a collection type.
    """

    origin = get_origin(annotation)
    return origin in (Union, UnionType, List, Tuple, Set, list, set, tuple)


def get_list_fields(model: type[BaseModel]) -> set[str]:
    return {
        name
        for name, field in model.model_fields.items()
        if is_list_type(field.annotation)
    }


def parse_form_encoded_body(
    request: HttpRequest, list_fields: set[str]
) -> dict[str, str | list[str] | None]:
    """
    Convert request.POST to a format pydantic can take as input
    """

    return {
        key: request.POST.getlist(key) if key in list_fields else request.POST.get(key)
        for key in request.POST
    }


def status_forbids_content(status: int) -> bool:
    """
    Whether a response with this status cannot carry content, per RFC 9112,
    section 6.3. Django's test client removes the body from these, so a test
    that goes through it cannot see one being written.
    """
    return 100 <= status < 200 or status in (204, 304)
