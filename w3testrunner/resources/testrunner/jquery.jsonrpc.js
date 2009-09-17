// Downloaded from http://github.com/veged/jquery.jsonrpc/, by Sergey Berezhnoy
// Modified to use local json2.js file.

(function($){

$.jsonRpc = $.jsonRpc || function(options) {
    options.type = options.type || 'GET';
    var ajaxOptions = {
        contentType: 'application/json',
        dataType:  options.type == 'GET' ? 'jsonp' : 'json',
        processData: options.type == 'GET'
    };

    var data = {
        version: options.version || '1.0',
        method: options.method || 'system.listMethods',
        params: options.params || []
    };
    $.each(data, function(i){ delete options[i] });

    function send() {
        options.data = JSON.stringify(data);
        if (options.type == 'GET') options.data = {json: options.data};
        $.ajax($.extend(ajaxOptions, options));
    }

    if (typeof JSON == 'undefined') {
        $.getScript('/testrunner/json2.js', function(){ send() });
    } else {
        send();
    }
    return $;
};

})(jQuery);
