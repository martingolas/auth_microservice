import re
from django.http import (
        HttpResponseNotAllowed,
        HttpResponseBadRequest,
        JsonResponse,
        HttpResponseNotFound,
        HttpResponseForbidden)
from django.views.decorators.http import require_http_methods
from . import models
from . import redirect_handler
from . import config
from . import util

@require_http_methods(['GET'])
def create_key(request):
    authorization = request.META.get('HTTP_AUTHORIZATION')
    print('create_key authorization: ' + authorization)
    m = re.match(r'^Basic (\w{64})', authorization)
    if m:
        received_key = m.group(1)
        if received_key != config.admin_key:
            HttpResponseForbidden('must provide admin credentials')
    else:
        return HttpResponseForbidden('must provide credentials')
    
    owner = request.GET.get('owner')
    if not owner:
        return HttpResponseBadRequest('must provider owner string')
    key = util.generate_nonce(64)
    db_entry = models.API_key(key=key, owner=owner)
    db_entry.save()
    return JsonResponse(status=200, data={'key': key})


def isint(s):
    try:
        i = int(s)
        return True
    except ValueError:
        return False

def _get_tokens(uid, scopes, provider):
    print('querying for tokens(uid,scopes,provider): ({},{},{})'.format(uid,scopes,provider))
    return models.Token.objects.filter(
        user__id=uid,
        scopes__in=models.Scope.objects.filter(name__in=scopes),
        provider=provider
    )

def _thread_block(lock, timeout):
    with lock:
        lock.wait(timeout)

def _valid_api_key(request):
    authorization = request.META.get('HTTP_AUTHORIZATION')
    print('_valid_api_key authorization: ' + authorization)
    m = re.match(r'^Basic (\w{64})', authorization) 
    if m:
        received_key = m.group(1)
        # key fields are encrypted, so we cannot natively filter, must be decrypted first
        keys = models.API_key.objects.filter(enabled=True)
        for db_key in keys:
            if db_key.key == received_key:
                return True
    return False
        

@require_http_methods(['GET'])
def token(request):
    # api key authentication
    if not _valid_api_key(request):
        return HttpResponseForbidden('must provide valid api key')
    
    uid = request.GET.get('uid')
    scope = request.GET.get('scope')
    provider = request.GET.get('provider')
    block = request.GET.get('block')
    
    # validate
    if block:
        if isint(block):
            block = int(block)
        elif block.lower() == 'false':
            block = False
        else:
            return HttpResponseBadRequest('if block param included, must be false or an integer')
    
    if not uid:
        return HttpResponseBadRequest('missing uid')

    if scope:
        scopes = scope.split(' ')
        if len(scopes) == 0:
            return HttpResponseBadRequest('no scopes provided')
    else:
        return HttpResponseBadRequest('missing scope')

    if not provider:
        return HttpResponseBadRequest('missing provider')
    
    tokens = _get_tokens(uid, scopes, provider)
    
    if tokens.count() == 0:
        print('no tokens met criteria')
        # no existing token matches these parameters
        handler = redirect_handler.RedirectHandler()
        if block:
            print('attempting block as required by client')
            #TODO block functionality
            lock = handler.block(uid, scopes, provider)
            if not lock:  #TODO clean this logic up
                print('no lock returned from handler.block')
                return HttpResponseNotFound('no token which meets required criteria')
            with lock:
                print('waiting for {} seconds'.format(block))
                lock.wait(block)
                # see if it was actually satisfied, or just woken up for timeout
                tokens = _get_tokens(uid, scopes, provider)
                if len(tokens) == 0:
                    return HttpResponseNotFound('no token which meets required criteria')
                # fall through
        else:
            # new authorization for this user and scopes
            url = handler.add(uid, scopes, provider)
            return JsonResponse(status=401, data={'authorization_url': url})

    if tokens.count() > 1:
        token = prune_duplicate_tokens(tokens)
    else:
        token = tokens[0]

    return JsonResponse(status=200, data={'access_token': token.access_token})

def prune_duplicate_tokens(tokens):
    pass    


def authcallback(request):
    #authorization_code = request.GET.get('code')
    #state = request.GET.get('state')
    
    # check state against active list
    # get provider corresponding to the state
    # exchange code for token response via that provider's token endpoint
    handler = redirect_handler.RedirectHandler()
    red_resp = handler.accept(request)
    
    # handler.accept returns a Django response or throws an exception
    return red_resp
