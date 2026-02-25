class AgentopsMcpServer < Formula
  include Language::Python::Virtualenv

  desc "AgentOps MCP Server"
  homepage "https://github.com/rioriost/homebrew-agentops_mcp_server/"
  url "https://files.pythonhosted.org/packages/06/e9/93269adfb52727fd15fb9c225807ac81e435a1512d132a637bf65a3c9eea/agentops_mcp_server-0.0.7.tar.gz"
  sha256 "0dbae5ecafaae54186b5bc71f3d676414a894e0f78ace58a1155c7f45ac92300"
  license "MIT"

  depends_on "python@3.14"

  def install
    virtualenv_install_with_resources
  end

  test do
    system "#{bin}/agentops_mcp_server", "--help"
  end
end
